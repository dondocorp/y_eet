"""
Base scraper contract.
All platform scrapers inherit from BaseScraper.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

from playwright.async_api import (
    Browser,
    BrowserContext,
    Page,
    Playwright,
    async_playwright,
    TimeoutError as PlaywrightTimeout,
)

from config.settings import (
    SCRAPER_HEADLESS,
    SCRAPER_MAX_RETRIES,
    SCRAPER_PAGE_TIMEOUT_MS,
    SCRAPER_RATE_LIMIT_DELAY_S,
)

logger = logging.getLogger(__name__)

NOISE_RE = re.compile(
    r"(RT @\w+:|Follow us|Subscribe now|Check out our|"
    r"Download the app|Limited time offer|Click the link|"
    r"t\.co/\w+)",
    re.IGNORECASE,
)


@dataclass
class RawPost:
    platform: str
    post_id: str
    raw_text: str
    author_handle: Optional[str] = None
    author_followers: Optional[int] = None
    post_url: Optional[str] = None
    posted_at: Optional[str] = None   # ISO8601 UTC
    likes: int = 0
    reposts: int = 0
    replies: int = 0
    upvotes: int = 0
    subreddit: Optional[str] = None
    language: str = "en"


@dataclass
class ScrapeResult:
    platform: str
    query: str
    posts: list[RawPost] = field(default_factory=list)
    error: Optional[str] = None
    duration_ms: int = 0
    pages_scraped: int = 0


class BaseScraper(ABC):
    """
    Contract:
      - Implement `scrape(query, max_posts)` as an async generator
      - Call `_noise_filter(text)` before yielding
      - Call `_rate_limit()` between page fetches
      - Handle retries via `_with_retry(coro)`
      - All timestamps must be UTC ISO8601
    """

    platform: str = "unknown"

    def __init__(self) -> None:
        self._pw: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None

    async def __aenter__(self) -> "BaseScraper":
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(
            headless=SCRAPER_HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
            ],
        )
        self._context = await self._browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="UTC",
        )
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    # ── Abstract interface ──────────────────────────────────────────────────

    @abstractmethod
    async def scrape(
        self, query: str, max_posts: int = 100
    ) -> AsyncIterator[RawPost]:
        """Yield RawPost objects for the given query."""
        ...

    async def scrape_all(self, query: str, max_posts: int = 100) -> ScrapeResult:
        t0 = time.time()
        posts: list[RawPost] = []
        error: Optional[str] = None
        pages = 0
        try:
            async for post in self.scrape(query, max_posts):
                posts.append(post)
                if len(posts) >= max_posts:
                    break
            pages = len(posts) // 20 + 1
        except Exception as exc:
            error = str(exc)
            logger.error(
                "scraper_error",
                extra={"platform": self.platform, "query": query, "error": str(exc)},
            )
        return ScrapeResult(
            platform=self.platform,
            query=query,
            posts=posts,
            error=error,
            duration_ms=int((time.time() - t0) * 1000),
            pages_scraped=pages,
        )

    # ── Shared utilities ────────────────────────────────────────────────────

    async def _new_page(self) -> Page:
        assert self._context is not None
        page = await self._context.new_page()
        page.set_default_timeout(SCRAPER_PAGE_TIMEOUT_MS)
        return page

    async def _rate_limit(self) -> None:
        await asyncio.sleep(SCRAPER_RATE_LIMIT_DELAY_S)

    async def _with_retry(self, coro_fn, *args, **kwargs):
        """Retry an async call up to SCRAPER_MAX_RETRIES times with backoff."""
        last_exc: Optional[Exception] = None
        for attempt in range(SCRAPER_MAX_RETRIES):
            try:
                return await coro_fn(*args, **kwargs)
            except (PlaywrightTimeout, Exception) as exc:
                last_exc = exc
                wait = 2 ** attempt
                logger.warning(
                    "scraper_retry",
                    extra={
                        "platform": self.platform,
                        "attempt": attempt + 1,
                        "wait_s": wait,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(wait)
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _noise_filter(text: str) -> Optional[str]:
        """Return None if post is junk; return cleaned text otherwise."""
        if not text or len(text.strip()) < 10:
            return None
        if NOISE_RE.search(text):
            return None
        return text.strip()

    @staticmethod
    def _utcnow() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _parse_count(value: str) -> int:
        """Parse '1.2K', '34K', '1M' etc. into int."""
        if not value:
            return 0
        value = value.strip().upper().replace(",", "")
        try:
            if value.endswith("K"):
                return int(float(value[:-1]) * 1_000)
            if value.endswith("M"):
                return int(float(value[:-1]) * 1_000_000)
            return int(value)
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _safe_post_id(url_or_id: str) -> str:
        """Extract a stable ID from a URL or return the raw string."""
        # Twitter: /status/1234567890
        m = re.search(r"/status/(\d+)", url_or_id)
        if m:
            return m.group(1)
        # Reddit: /comments/abc123/
        m = re.search(r"/comments/([a-z0-9]+)/", url_or_id)
        if m:
            return m.group(1)
        return re.sub(r"[^a-zA-Z0-9_\-]", "", url_or_id)[:64]
