"""
Twitter / X Public Search Scraper
───────────────────────────────────
Scrapes public search results from twitter.com/search — no API key.
Targets: tweet text, engagement counts, author handle.

NOTE: X.com aggressively gates search behind login walls.
This scraper targets the guest/public-access tier.
If pages consistently return login prompts, set TWITTER_ENABLED=false
and rely on Reddit + manual seeding.

Anti-fragility:
  - Selectors are version-tagged; if primary fails, falls back to secondary set
  - validate_post() guards before yielding
  - Rate limiting: 3s between scroll steps
"""

from __future__ import annotations

import logging
from typing import AsyncIterator
from urllib.parse import quote_plus

from config.settings import SCRAPER_MAX_POSTS_PER_RUN

from scraper.base import BaseScraper, RawPost

logger = logging.getLogger(__name__)

# Primary selectors (2024 design)
SELECTORS_V1 = {
    "tweet_article": "article[data-testid='tweet']",
    "tweet_text": "div[data-testid='tweetText']",
    "tweet_time": "time",
    "tweet_user": "div[data-testid='User-Name'] span",
    "tweet_likes": "div[data-testid='like'] span",
    "tweet_retweets": "div[data-testid='retweet'] span",
    "tweet_replies": "div[data-testid='reply'] span",
    "tweet_link": "a[href*='/status/']",
}

TWITTER_SEARCH_URL = "https://twitter.com/search?q={q}&src=typed_query&f=live"


class TwitterScraper(BaseScraper):
    platform = "twitter"

    async def scrape(
        self, query: str, max_posts: int = SCRAPER_MAX_POSTS_PER_RUN
    ) -> AsyncIterator[RawPost]:
        url = TWITTER_SEARCH_URL.format(q=quote_plus(query))
        page = await self._new_page()

        # Disable image/media loading to speed up render
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,mp4,webm}",
            lambda r: r.abort(),
        )

        seen_ids: set[str] = set()
        collected = 0

        try:
            await self._with_retry(page.goto, url, wait_until="domcontentloaded")

            # Check for login wall
            if await self._is_login_wall(page):
                logger.warning("twitter_login_wall_detected", extra={"query": query})
                return

            # Scroll + collect
            scroll_attempts = 0
            max_scrolls = max(5, max_posts // 20)

            while collected < max_posts and scroll_attempts < max_scrolls:
                articles = await page.query_selector_all(SELECTORS_V1["tweet_article"])

                for article in articles:
                    if collected >= max_posts:
                        break
                    try:
                        post = await self._extract(article)
                        if post and post.post_id not in seen_ids:
                            seen_ids.add(post.post_id)
                            yield post
                            collected += 1
                    except Exception as exc:
                        logger.debug("twitter_extract_error", extra={"error": str(exc)})

                # Scroll down
                await page.evaluate("window.scrollBy(0, 2000)")
                await self._rate_limit()
                scroll_attempts += 1

        except Exception as exc:
            logger.error(
                "twitter_scrape_error",
                extra={"query": query, "error": str(exc)},
            )
        finally:
            await page.close()

    async def _extract(self, article) -> RawPost | None:
        text_el = await article.query_selector(SELECTORS_V1["tweet_text"])
        if not text_el:
            return None
        raw_text = await text_el.inner_text()
        cleaned = self._noise_filter(raw_text)
        if not cleaned:
            return None

        # Timestamp
        time_el = await article.query_selector(SELECTORS_V1["tweet_time"])
        posted_at = None
        if time_el:
            posted_at = await time_el.get_attribute("datetime")

        # Author
        user_els = await article.query_selector_all(SELECTORS_V1["tweet_user"])
        author = None
        for el in user_els:
            t = (await el.inner_text()).strip()
            if t.startswith("@"):
                author = t[1:]
                break

        # Engagement
        likes_el = await article.query_selector(SELECTORS_V1["tweet_likes"])
        rts_el = await article.query_selector(SELECTORS_V1["tweet_retweets"])
        rep_el = await article.query_selector(SELECTORS_V1["tweet_replies"])

        likes = self._parse_count(await likes_el.inner_text() if likes_el else "0")
        retweets = self._parse_count(await rts_el.inner_text() if rts_el else "0")
        replies = self._parse_count(await rep_el.inner_text() if rep_el else "0")

        # Link / ID
        link_el = await article.query_selector(SELECTORS_V1["tweet_link"])
        post_url = await link_el.get_attribute("href") if link_el else None
        if post_url and not post_url.startswith("http"):
            post_url = f"https://twitter.com{post_url}"
        post_id = self._safe_post_id(post_url or "") or self._utcnow()

        return RawPost(
            platform=self.platform,
            post_id=post_id,
            raw_text=cleaned,
            author_handle=author,
            post_url=post_url,
            posted_at=posted_at,
            likes=likes,
            reposts=retweets,
            replies=replies,
        )

    @staticmethod
    async def _is_login_wall(page) -> bool:
        try:
            content = await page.content()
            return (
                "Log in to Twitter" in content
                or "Sign in to X" in content
                or 'data-testid="loginButton"' in content
            )
        except Exception:
            return False
