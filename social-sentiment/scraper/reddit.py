"""
Reddit Public Search Scraper
──────────────────────────────
Scrapes reddit.com/search public results — no API key required.
Targets: post titles, post bodies, and top-level comment text.

Anti-fragility:
  - Selectors defined in one place (SELECTORS dict) — update without touching logic
  - Falls back to JSON fallback endpoint (old.reddit.com + .json) if DOM scrape fails
  - Validates minimum field presence before yielding
"""

from __future__ import annotations

import json
import logging
import re
from typing import AsyncIterator, Optional
from urllib.parse import quote_plus

from config.settings import SCRAPER_MAX_POSTS_PER_RUN
from scraper.base import BaseScraper, RawPost

logger = logging.getLogger(__name__)

SELECTORS = {
    # New Reddit (shreddit / post-v2 design)
    "post_container": "shreddit-post",
    "post_title": "[slot='title']",
    "post_body": "[slot='text-body']",
    "post_id_attr": "id",  # attribute on shreddit-post element
    "post_permalink": "permalink",  # attribute on shreddit-post element
    "post_author": "author",  # attribute
    "post_score": "score",  # attribute
    "post_created": "created-timestamp",  # attribute (ISO string)
    "post_sub": "subreddit-prefixed-name",
    # Old Reddit fallback
    "old_posts": ".thing.link",
    "old_title": "a.title",
    "old_author": ".author",
    "old_score": ".score.unvoted",
}

REDDIT_SEARCH_TPL = "https://www.reddit.com/search/?q={q}&sort=new&t=day&type=link"
OLD_REDDIT_JSON = "https://www.reddit.com/search.json?q={q}&sort=new&t=day&limit=100"


class RedditScraper(BaseScraper):
    platform = "reddit"

    async def scrape(
        self, query: str, max_posts: int = SCRAPER_MAX_POSTS_PER_RUN
    ) -> AsyncIterator[RawPost]:
        # Try JSON endpoint first — fastest, most reliable
        async for post in self._scrape_json(query, max_posts):
            yield post
            max_posts -= 1
            if max_posts <= 0:
                return

        # If JSON didn't fill quota, try DOM scrape
        if max_posts > 0:
            async for post in self._scrape_dom(query, max_posts):
                yield post
                max_posts -= 1
                if max_posts <= 0:
                    return

    # ── JSON endpoint ───────────────────────────────────────────────────────

    async def _scrape_json(self, query: str, max_posts: int) -> AsyncIterator[RawPost]:
        url = OLD_REDDIT_JSON.format(q=quote_plus(query))
        page = await self._new_page()
        try:
            await self._with_retry(page.goto, url, wait_until="load")
            content = await page.content()
            # Playwright returns the JSON embedded in an HTML page
            m = re.search(r"<pre[^>]*>(.*?)</pre>", content, re.DOTALL)
            if not m:
                return
            data = json.loads(m.group(1))
            children = data.get("data", {}).get("children", [])
        except Exception as exc:
            logger.warning("reddit_json_failed", extra={"error": str(exc)})
            return
        finally:
            await page.close()

        count = 0
        for child in children:
            if count >= max_posts:
                break
            post = child.get("data", {})
            text = self._extract_text_json(post)
            if text is None:
                continue
            yield RawPost(
                platform=self.platform,
                post_id=post.get("id", ""),
                raw_text=text,
                author_handle=post.get("author"),
                post_url="https://www.reddit.com" + post.get("permalink", ""),
                posted_at=self._ts(post.get("created_utc")),
                upvotes=int(post.get("score", 0)),
                replies=int(post.get("num_comments", 0)),
                subreddit=post.get("subreddit_name_prefixed"),
                language="en",
            )
            count += 1
            await self._rate_limit()

    def _extract_text_json(self, post: dict) -> Optional[str]:
        title = post.get("title", "")
        selftext = post.get("selftext", "")
        combined = f"{title} {selftext}".strip()
        return self._noise_filter(combined)

    # ── DOM fallback ────────────────────────────────────────────────────────

    async def _scrape_dom(self, query: str, max_posts: int) -> AsyncIterator[RawPost]:
        url = REDDIT_SEARCH_TPL.format(q=quote_plus(query))
        page = await self._new_page()
        try:
            await self._with_retry(page.goto, url, wait_until="networkidle")
            await page.wait_for_selector(SELECTORS["post_container"], timeout=15000)
        except Exception as exc:
            logger.warning("reddit_dom_load_failed", extra={"error": str(exc)})
            await page.close()
            return

        count = 0
        try:
            elements = await page.query_selector_all(SELECTORS["post_container"])
            for el in elements:
                if count >= max_posts:
                    break
                try:
                    title_el = await el.query_selector(SELECTORS["post_title"])
                    body_el = await el.query_selector(SELECTORS["post_body"])
                    title = (await title_el.inner_text()).strip() if title_el else ""
                    body = (await body_el.inner_text()).strip() if body_el else ""
                    text = self._noise_filter(f"{title} {body}".strip())
                    if not text:
                        continue

                    post_id = await el.get_attribute(SELECTORS["post_id_attr"]) or ""
                    permalink = (
                        await el.get_attribute(SELECTORS["post_permalink"]) or ""
                    )
                    author = await el.get_attribute(SELECTORS["post_author"])
                    score_raw = await el.get_attribute(SELECTORS["post_score"]) or "0"
                    created = await el.get_attribute(SELECTORS["post_created"])
                    sub = await el.get_attribute(SELECTORS["post_sub"])

                    yield RawPost(
                        platform=self.platform,
                        post_id=self._safe_post_id(post_id or permalink),
                        raw_text=text,
                        author_handle=author,
                        post_url=f"https://www.reddit.com{permalink}",
                        posted_at=created or self._utcnow(),
                        upvotes=self._parse_count(score_raw),
                        subreddit=sub,
                    )
                    count += 1
                    await self._rate_limit()
                except Exception as exc:
                    logger.debug("reddit_dom_post_error", extra={"error": str(exc)})
        finally:
            await page.close()

    @staticmethod
    def _ts(unix: Optional[float]) -> Optional[str]:
        if unix is None:
            return None
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(unix), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
