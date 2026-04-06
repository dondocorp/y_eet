"""Tests for scraper base utilities — no browser required."""
import pytest
from scraper.base import BaseScraper


class _MockScraper(BaseScraper):
    platform = "test"

    async def scrape(self, query, max_posts=100):
        yield  # pragma: no cover


clf = _MockScraper()


class TestNoiseFilter:
    def test_too_short_returns_none(self):
        assert BaseScraper._noise_filter("hi") is None

    def test_promotional_noise_excluded(self):
        assert BaseScraper._noise_filter("RT @someone: Subscribe now link") is None

    def test_valid_text_passes(self):
        result = BaseScraper._noise_filter("Yeet Casino withdrawal stuck for 3 days, very frustrated")
        assert result is not None
        assert len(result) > 10


class TestParseCount:
    def test_plain_number(self):
        assert BaseScraper._parse_count("1234") == 1234

    def test_k_suffix(self):
        assert BaseScraper._parse_count("1.2K") == 1200

    def test_m_suffix(self):
        assert BaseScraper._parse_count("2M") == 2_000_000

    def test_empty_string(self):
        assert BaseScraper._parse_count("") == 0

    def test_comma_separated(self):
        assert BaseScraper._parse_count("10,000") == 10_000


class TestSafePostId:
    def test_twitter_status_url(self):
        pid = BaseScraper._safe_post_id("https://twitter.com/user/status/1234567890")
        assert pid == "1234567890"

    def test_reddit_comments_url(self):
        pid = BaseScraper._safe_post_id("https://reddit.com/r/gambling/comments/abc123/post")
        assert pid == "abc123"

    def test_raw_id_passthrough(self):
        pid = BaseScraper._safe_post_id("raw_id_12345")
        assert pid == "raw_id_12345"
