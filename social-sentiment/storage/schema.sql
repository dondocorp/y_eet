-- ============================================================
-- Social Sentiment Subsystem — SQLite Schema
-- ============================================================
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA synchronous = NORMAL;

-- ── scrape_runs ──────────────────────────────────────────────
-- One row per scheduled pipeline execution.
CREATE TABLE IF NOT EXISTS scrape_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL UNIQUE,          -- uuid4
    platform     TEXT    NOT NULL,                 -- twitter|reddit|youtube
    query        TEXT    NOT NULL,                 -- search term used
    started_at   TEXT    NOT NULL,                 -- ISO8601 UTC
    finished_at  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running', -- running|success|failed
    posts_found  INTEGER NOT NULL DEFAULT 0,
    error_msg    TEXT,
    duration_ms  INTEGER,
    created_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE INDEX IF NOT EXISTS idx_scrape_runs_platform_started ON scrape_runs(platform, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_scrape_runs_status           ON scrape_runs(status);

-- ── raw_posts ────────────────────────────────────────────────
-- Immutable raw data exactly as collected.
CREATE TABLE IF NOT EXISTS raw_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         TEXT    NOT NULL,              -- platform-native ID
    platform        TEXT    NOT NULL,              -- twitter|reddit|youtube
    scrape_run_id   TEXT    NOT NULL REFERENCES scrape_runs(run_id),
    raw_text        TEXT    NOT NULL,
    author_handle   TEXT,
    author_followers INTEGER,
    post_url        TEXT,
    posted_at       TEXT,                          -- ISO8601 UTC as reported by platform
    scraped_at      TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    likes           INTEGER DEFAULT 0,
    reposts         INTEGER DEFAULT 0,
    replies         INTEGER DEFAULT 0,
    upvotes         INTEGER DEFAULT 0,
    subreddit       TEXT,                          -- Reddit only
    language        TEXT    DEFAULT 'en',
    UNIQUE(platform, post_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_posts_platform_posted ON raw_posts(platform, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_posts_scraped_at      ON raw_posts(scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_posts_run             ON raw_posts(scrape_run_id);

-- Retention: keep raw_posts for 90 days, then purge.

-- ── normalized_posts ─────────────────────────────────────────
-- Cleaned, deduplicated version. One row per unique post.
CREATE TABLE IF NOT EXISTS normalized_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_post_id     INTEGER NOT NULL REFERENCES raw_posts(id),
    platform        TEXT    NOT NULL,
    post_id         TEXT    NOT NULL,
    clean_text      TEXT    NOT NULL,              -- whitespace-stripped, emoji normalised
    char_count      INTEGER,
    word_count      INTEGER,
    lang_detected   TEXT,
    posted_at       TEXT,
    normalized_at   TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(platform, post_id)
);

CREATE INDEX IF NOT EXISTS idx_norm_platform_posted ON normalized_posts(platform, posted_at DESC);

-- ── classifier_runs ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS classifier_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL UNIQUE,
    scrape_run_id TEXT,
    classifier   TEXT    NOT NULL,                 -- relevance|sentiment
    model_name   TEXT    NOT NULL,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running',
    posts_processed INTEGER DEFAULT 0,
    error_msg    TEXT,
    duration_ms  INTEGER
);

-- ── sentiment_results ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentiment_results (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    normalized_post_id  INTEGER NOT NULL REFERENCES normalized_posts(id),
    platform            TEXT    NOT NULL,
    post_id             TEXT    NOT NULL,
    classifier_run_id   TEXT    REFERENCES classifier_runs(run_id),

    -- Relevance
    is_relevant         INTEGER NOT NULL DEFAULT 0,  -- 0|1
    relevance_score     REAL    NOT NULL DEFAULT 0.0, -- 0.0–1.0
    relevance_method    TEXT,                         -- keyword|embedding|hybrid

    -- Sentiment
    sentiment_label     TEXT,    -- positive|neutral|negative
    sentiment_score     REAL,    -- confidence 0.0–1.0
    sentiment_raw_pos   REAL,
    sentiment_raw_neu   REAL,
    sentiment_raw_neg   REAL,

    -- Derived labels (JSON array of matched tags)
    derived_labels      TEXT DEFAULT '[]',  -- ["payment_issue","scam_concern",...]

    -- Influence weight (normalised 0–1 for weighted aggregation)
    influence_weight    REAL DEFAULT 1.0,

    classified_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    posted_at           TEXT,

    UNIQUE(platform, post_id)
);

CREATE INDEX IF NOT EXISTS idx_sent_platform_posted    ON sentiment_results(platform, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_sent_relevant           ON sentiment_results(is_relevant, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_sent_label              ON sentiment_results(sentiment_label, posted_at DESC);
CREATE INDEX IF NOT EXISTS idx_sent_classified_at      ON sentiment_results(classified_at DESC);

-- ── hourly_aggregates ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS hourly_aggregates (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    hour_bucket             TEXT NOT NULL,  -- ISO8601 truncated to hour: 2024-01-15T14:00:00Z
    platform                TEXT NOT NULL,  -- twitter|reddit|youtube|ALL
    brand_query             TEXT NOT NULL,  -- yeet|yeet-casino|yeet.com
    total_posts             INTEGER DEFAULT 0,
    relevant_posts          INTEGER DEFAULT 0,
    positive_count          INTEGER DEFAULT 0,
    neutral_count           INTEGER DEFAULT 0,
    negative_count          INTEGER DEFAULT 0,
    avg_sentiment_score     REAL,           -- mean of sentiment_score for relevant posts
    weighted_sentiment      REAL,           -- influence-weighted sentiment
    pos_ratio               REAL,
    neu_ratio               REAL,
    neg_ratio               REAL,
    top_derived_labels      TEXT DEFAULT '{}',  -- JSON: {label: count}
    avg_influence           REAL,
    computed_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(hour_bucket, platform, brand_query)
);

CREATE INDEX IF NOT EXISTS idx_hourly_bucket_platform ON hourly_aggregates(hour_bucket DESC, platform);
CREATE INDEX IF NOT EXISTS idx_hourly_brand           ON hourly_aggregates(brand_query, hour_bucket DESC);

-- Retention: keep hourly_aggregates forever (tiny rows).

-- ── alert_events ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS alert_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_id        TEXT    NOT NULL UNIQUE,    -- dedup key
    alert_name      TEXT    NOT NULL,
    severity        TEXT    NOT NULL,           -- critical|warning|info
    platform        TEXT,
    brand_query     TEXT,
    trigger_value   REAL,
    threshold       REAL,
    message         TEXT    NOT NULL,
    payload_json    TEXT,                       -- full payload sent to webhook
    fired_at        TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    resolved_at     TEXT,
    suppressed      INTEGER DEFAULT 0,
    sent_ok         INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_alert_fired   ON alert_events(fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_name    ON alert_events(alert_name, fired_at DESC);
CREATE INDEX IF NOT EXISTS idx_alert_sev     ON alert_events(severity, fired_at DESC);
