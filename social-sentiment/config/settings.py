"""
Central config pulled from environment variables.
Loaded once at startup; immutable after.
"""
from __future__ import annotations

import os
from pathlib import Path

# ── Brand / Query ────────────────────────────────────────────────────────────
BRAND_QUERIES: list[str] = os.getenv(
    "BRAND_QUERIES", "yeet,yeet casino,yeet.com"
).split(",")

TARGET_BRAND_PRIMARY: str = os.getenv("TARGET_BRAND_PRIMARY", "yeet casino")

# ── Storage ──────────────────────────────────────────────────────────────────
DATA_DIR = Path(os.getenv("DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "social_sentiment.db"

# ── Scraper ──────────────────────────────────────────────────────────────────
SCRAPER_ENABLED_PLATFORMS: list[str] = os.getenv(
    "SCRAPER_ENABLED_PLATFORMS", "reddit,twitter"
).split(",")
SCRAPER_MAX_POSTS_PER_RUN: int = int(os.getenv("SCRAPER_MAX_POSTS_PER_RUN", "100"))
SCRAPER_PAGE_TIMEOUT_MS: int = int(os.getenv("SCRAPER_PAGE_TIMEOUT_MS", "30000"))
SCRAPER_RATE_LIMIT_DELAY_S: float = float(os.getenv("SCRAPER_RATE_LIMIT_DELAY_S", "2.0"))
SCRAPER_MAX_RETRIES: int = int(os.getenv("SCRAPER_MAX_RETRIES", "3"))
SCRAPER_HEADLESS: bool = os.getenv("SCRAPER_HEADLESS", "true").lower() == "true"

# Twitter / X search URL base (no auth, public search page)
TWITTER_SEARCH_URL: str = "https://twitter.com/search?q={query}&src=typed_query&f=live"

# Reddit search URL base
REDDIT_SEARCH_URL: str = "https://www.reddit.com/search/?q={query}&sort=new&t=day"

# ── NLP ──────────────────────────────────────────────────────────────────────
SENTIMENT_MODEL: str = os.getenv(
    "SENTIMENT_MODEL", "cardiffnlp/twitter-roberta-base-sentiment-latest"
)
RELEVANCE_EMBEDDING_MODEL: str = os.getenv(
    "RELEVANCE_EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
RELEVANCE_EMBEDDING_ENABLED: bool = (
    os.getenv("RELEVANCE_EMBEDDING_ENABLED", "false").lower() == "true"
)
RELEVANCE_EMBEDDING_THRESHOLD: float = float(
    os.getenv("RELEVANCE_EMBEDDING_THRESHOLD", "0.6")
)
CLASSIFIER_BATCH_SIZE: int = int(os.getenv("CLASSIFIER_BATCH_SIZE", "32"))
MODEL_CACHE_DIR: str = os.getenv("MODEL_CACHE_DIR", "/app/model_cache")

# ── Metrics ──────────────────────────────────────────────────────────────────
METRICS_PORT: int = int(os.getenv("METRICS_PORT", "9465"))
METRICS_PATH: str = os.getenv("METRICS_PATH", "/metrics")

# ── Alerting ─────────────────────────────────────────────────────────────────
ALERT_BACKEND: str = os.getenv("ALERT_BACKEND", "telegram")  # telegram|slack

# Telegram
TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

# Slack (fallback)
SLACK_WEBHOOK_URL: str = os.getenv("SLACK_WEBHOOK_URL", "")

# Alertmanager webhook (for Prometheus-native routing)
ALERTMANAGER_WEBHOOK_URL: str = os.getenv(
    "ALERTMANAGER_WEBHOOK_URL", "http://alertmanager:9093/api/v2/alerts"
)

# Alert thresholds
ALERT_NEG_RATIO_THRESHOLD: float = float(
    os.getenv("ALERT_NEG_RATIO_THRESHOLD", "0.40")
)
ALERT_NEG_RATIO_WINDOW_HOURS: int = int(
    os.getenv("ALERT_NEG_RATIO_WINDOW_HOURS", "1")
)
ALERT_MENTION_SPIKE_MULTIPLIER: float = float(
    os.getenv("ALERT_MENTION_SPIKE_MULTIPLIER", "3.0")
)
ALERT_SCAM_COUNT_THRESHOLD: int = int(os.getenv("ALERT_SCAM_COUNT_THRESHOLD", "5"))
ALERT_SUPPRESSION_MINUTES: int = int(os.getenv("ALERT_SUPPRESSION_MINUTES", "60"))

# ── OTEL / Tracing ───────────────────────────────────────────────────────────
OTEL_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "social-sentiment")
OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "true").lower() == "true"

# ── Logging ──────────────────────────────────────────────────────────────────
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT: str = os.getenv("LOG_FORMAT", "json")  # json|pretty
