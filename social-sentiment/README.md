# Brand Intelligence Pipeline

> Scrapes Reddit and Twitter for brand mentions, classifies relevance and sentiment,
> aggregates hourly trends, fires alerts, and surfaces signals into the Yeet Grafana
> observability portal as a dedicated Brand Intelligence domain.

This is not a standalone dashboard toy. It runs on a 30-minute cron schedule and is fully wired into the same observability stack (Prometheus, Grafana, OTEL Collector, Loki, Alertmanager) as the rest of the platform.

---

## Overview

| Layer | What it does |
|---|---|
| **Scrapers** | Playwright-based Reddit + Twitter crawlers — no API keys required |
| **Relevance filtering** | 5-stage keyword pipeline tuned for an ambiguous brand name ("Yeet") |
| **Sentiment classification** | `cardiffnlp/twitter-roberta-base-sentiment-latest` — 3-class, CPU-only, ~500 MB |
| **Aggregation** | Hourly rollup: mention counts, sentiment ratios, influence-weighted score, label frequency |
| **Alerting** | 7 alert rules, dual-path via Telegram + Alertmanager, suppression + dedup built in |
| **Metrics** | 13 Prometheus metrics on `:9465/metrics`, scraped by the existing Prometheus instance |
| **Analyst UI** | Streamlit on `:8501` — post explorer, top negatives, complaint clusters |

---

## Architecture

```
[scheduler every 30m]
       │
       ▼
 Scrapers (Playwright)
 ├── reddit.py   — JSON endpoint + DOM fallback
 └── twitter.py  — public search, scroll-based
       │
       ▼
 Normalizer      — deduplicate, clean text, persist raw_posts
       │
       ▼
 Relevance Classifier  — 5-stage keyword pipeline + optional embedding gate
 ├── Hard exclusions     (yeet baby, yeet meme, yeet fortnite, ...)
 ├── Primary match       (yeet casino, yeetcasino, yeet.com, ...)  → score ≥ 0.85
 ├── Secondary + context (yeet + casino/gambling/deposit/...)       → score ≥ 0.55
 └── Derived labels      (scam_concern, payment_issue, ux_praise, hype, ...)
       │  relevant posts only
       ▼
 Sentiment Classifier  — cardiffnlp/twitter-roberta-base-sentiment-latest
 └── 3-class: positive / neutral / negative
       │
       ▼
 SQLite DB (WAL mode)
 ├── sentiment_results, hourly_aggregates, alert_events
 │
 ├──▶ Hourly Aggregation  — ratios, weighted sentiment, label counts
 ├──▶ Alert Evaluator     — threshold checks → Telegram + Alertmanager
 └──▶ Prometheus /metrics — social_* family → Grafana Brand Intelligence dashboards
```

---

## Quick Start

```bash
# Copy and configure environment
cp .env.example .env
# Required: TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID

# Start via Docker Compose (from repo root)
docker compose up social-sentiment social-sentiment-dashboard

# Or run locally
pip install -r requirements.txt
playwright install chromium
python scripts/init_db.py
python -m pipeline.ingest       # single pipeline run
python scripts/scheduler.py     # continuous 30-minute scheduler
```

**Seed demo data** (bypasses scraper and ML — populates dashboards instantly):

```bash
PYTHONPATH=. python3 scripts/seed_demo.py          # skips if data already exists
PYTHONPATH=. python3 scripts/seed_demo.py --force  # re-seed unconditionally
```

**Diagnose Reddit reachability and relevance pass-through** (no DB writes by default):

```bash
PYTHONPATH=. python3 scripts/test_fetch.py
PYTHONPATH=. python3 scripts/test_fetch.py --query "yeet casino" --limit 20 --write
```

### Service Endpoints

| Endpoint | URL |
|---|---|
| Prometheus metrics | `http://localhost:9465/metrics` |
| Health check | `http://localhost:9465/health` |
| Streamlit analyst UI | `http://localhost:8501` |
| Grafana Brand Intelligence | `http://localhost:3000` → Brand Intelligence folder |

---

## Configuration

All configuration is driven by environment variables. Copy `.env.example` to `.env` to get started.

| Variable | Default | Description |
|---|---|---|
| `BRAND_QUERIES` | `yeet casino,yeet.com,yeetcasino` | Comma-separated search queries |
| `SCRAPER_ENABLED_PLATFORMS` | `reddit,twitter` | Active scrapers |
| `SCRAPER_MAX_POSTS_PER_RUN` | `100` | Max posts per query per run |
| `SCRAPER_RATE_LIMIT_DELAY_S` | `2.0` | Seconds between page fetches |
| `SENTIMENT_MODEL` | `cardiffnlp/twitter-roberta-base-sentiment-latest` | HuggingFace model ID |
| `RELEVANCE_EMBEDDING_ENABLED` | `false` | Enable embedding gate for borderline posts |
| `ALERT_NEG_RATIO_THRESHOLD` | `0.40` | Negative ratio that triggers a warning alert |
| `ALERT_SCAM_COUNT_THRESHOLD` | `5` | Scam-labelled posts per hour for a critical alert |
| `ALERT_SUPPRESSION_MINUTES` | `60` | Minimum minutes between duplicate alerts |
| `SCHEDULER_INTERVAL_MINUTES` | `30` | Pipeline run frequency |
| `TELEGRAM_BOT_TOKEN` | — | Required for alert delivery |
| `TELEGRAM_CHAT_ID` | — | Required for alert delivery |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTEL Collector gRPC endpoint |

---

## Directory Structure

```
social-sentiment/
├── scraper/
│   ├── base.py             BaseScraper — Playwright contract, retry, noise filter, rate limiting
│   ├── reddit.py           Reddit JSON endpoint + DOM fallback
│   └── twitter.py          Twitter public search, scroll-based, login-wall detection
│
├── nlp/
│   ├── relevance.py        5-stage relevance pipeline with derived label classification
│   └── sentiment.py        RoBERTa wrapper — batch inference, model caching, failure fallback
│
├── storage/
│   ├── schema.sql          SQLite DDL — 7 tables, indexes, WAL pragma
│   └── db.py               Typed sqlite3 access layer — no ORM
│
├── pipeline/
│   ├── ingest.py           Scrape → normalize → classify → persist (with OTEL spans)
│   └── aggregate.py        Hourly rollup — ratios, weighted sentiment, spike detection
│
├── alerts/
│   ├── evaluator.py        Alert rules, suppression/dedup, metric increments
│   └── sender.py           Telegram MarkdownV2 sender + Alertmanager /api/v2/alerts push
│
├── metrics/
│   └── exporter.py         13 Prometheus metrics, lightweight HTTPServer on :9465
│
├── observability/
│   ├── tracer.py           OTEL TracerProvider → existing collector
│   └── logger.py           JSON structured logger (Loki-compatible)
│
├── config/
│   ├── settings.py         All env var config — single import point
│   └── keywords.yaml       Brand keyword rules — primary, secondary, exclusions, derived labels
│
├── dashboard/
│   └── app.py              Streamlit app — 5 tabs: Overview, Post Explorer, Top Negatives,
│                           Complaint Clusters, Alert Log
│
├── scripts/
│   ├── scheduler.py        In-process scheduler — startup check, pipeline loop, daily purge
│   ├── seed_demo.py        Inserts synthetic demo data into all pipeline tables (bypasses ML)
│   ├── test_fetch.py       Diagnostic — Reddit reachability, relevance pass-through, DB round-trip
│   ├── run_pipeline.sh     Shell entrypoint for host-level cron
│   └── init_db.py          Idempotent DB initializer
│
└── tests/
    ├── conftest.py
    ├── test_relevance.py
    ├── test_scraper_parser.py
    ├── test_storage.py
    ├── test_aggregation.py
    ├── test_alerts.py
    └── test_metrics.py
```

---

## Data Model

Seven SQLite tables with WAL mode enabled:

| Table | Purpose | Retention |
|---|---|---|
| `scrape_runs` | One row per pipeline execution, with status and duration | Permanent |
| `raw_posts` | Immutable raw scraped data | 90 days |
| `normalized_posts` | Cleaned, deduplicated posts | 90 days |
| `classifier_runs` | Classifier batch metadata | Permanent |
| `sentiment_results` | Relevance + sentiment scores + derived labels per post | 90 days |
| `hourly_aggregates` | Rolled-up stats per hour / platform / brand | Permanent |
| `alert_events` | Fired alerts with dedup key, payload, and send status | 30 days |

Deduplication is enforced at the database level via `UNIQUE(platform, post_id)` on `raw_posts` and `sentiment_results`.

> **SQLite datetime note:** All datetime comparisons use `datetime('now', '-N days')` string comparison against ISO-8601 stored strings. The schema stores `created_at` as text in `YYYY-MM-DD HH:MM:SS` format — this is intentional and consistent throughout the access layer. Do not cast to a numeric timestamp.

---

## Relevance Filtering

"Yeet" is a highly ambiguous term. The 5-stage pipeline is essential for noise reduction:

```
Input text
    │
    ├─ Hard exclusion match?   →  score = 0.0  →  IRRELEVANT
    │  (yeet baby, yeet meme, yeet fortnite, ...)
    │
    ├─ Primary keyword match?  →  score ≥ 0.85 →  RELEVANT
    │  (yeet casino, yeetcasino, yeet.com casino, ...)
    │
    ├─ Secondary + context?    →  score ≥ 0.55 →  RELEVANT
    │  (yeet + casino / slots / deposit / withdrawal / bonus, ...)
    │
    ├─ Secondary only?         →  score ≤ 0.35
    │  └─ Embedding gate on?   →  cosine sim ≥ 0.6  →  RELEVANT
    │                          →  else               →  IRRELEVANT
    │
    └─ No match                →  score = 0.0  →  IRRELEVANT
```

Edit `config/keywords.yaml` to tune inclusion and exclusion rules without touching code.

---

## Alert Rules

| Alert | Severity | Trigger condition |
|---|---|---|
| `NegativeSentimentSpike` | warning | neg_ratio > 40% with ≥ 3 relevant posts |
| `NegativeSentimentCritical` | critical | neg_ratio > 65% with ≥ 5 relevant posts |
| `ScamConcernSpike` | critical | `scam_concern` label count > 5 in the last hour |
| `PaymentIssueSurge` | warning | `payment_issue` label count > 10 in the last hour |
| `MentionVolumeSpike` | warning | Mentions > 3× the 7-day rolling median |
| `ScrapeFailure` | warning | All runs failed with no success in the last 2 hours |
| `NoDataAnomaly` | warning | Zero relevant posts for 2+ consecutive hours |

All alerts are:
- **Suppressed** for `ALERT_SUPPRESSION_MINUTES` (default 60) after firing to prevent noise floods
- **Deduplicated** by SHA-256 of `{alert_name}:{platform}:{brand_query}:{hour_bucket}`
- **Dual-path** — sent via Telegram AND pushed to Alertmanager for existing on-call routing

---

## Prometheus Metrics

All metrics are prefixed `social_` and exposed on `:9465/metrics`.

| Metric | Type | Labels |
|---|---|---|
| `social_scrape_runs_total` | Counter | `platform` |
| `social_scrape_failures_total` | Counter | `platform` |
| `social_posts_collected_total` | Counter | `platform` |
| `social_posts_relevant_total` | Counter | `platform` |
| `social_posts_irrelevant_total` | Counter | `platform` |
| `social_sentiment_positive_total` | Counter | `platform` |
| `social_sentiment_negative_total` | Counter | `platform` |
| `social_sentiment_neutral_total` | Counter | `platform` |
| `social_alerts_triggered_total` | Counter | `alert_name`, `severity` |
| `social_pipeline_duration_seconds` | Histogram | `stage` |
| `social_brand_relevance_confidence_bucket` | Histogram | — |
| `social_classifier_failures_total` | Counter | `classifier` |
| `social_pipeline_last_run_timestamp` | Gauge | — |

---

## Grafana Dashboards

Three dashboards are auto-provisioned into the **Brand Intelligence** folder:

| Dashboard | Audience | Refresh rate |
|---|---|---|
| Executive View | Leadership, Marketing | 5m |
| Operations View | On-call, SRE | 1m |
| Pipeline Health | Data Engineering, SRE | 30s |

**Executive View** — KPI stats (total mentions, positive %, negative %, active alerts), 24h mention volume bar chart, sentiment ratio area chart, weighted sentiment trend, 7-day alert history.

**Operations View** — Active alert list, scraper success rate, real-time negative ratio with threshold lines (40% warning / 65% critical), pipeline duration p50/p99, live Loki log panel.

**Pipeline Health** — Service up/down indicator, pipeline last-run age, classifier failure rate table, relevance confidence distribution, collected vs. relevant post rates, Tempo trace viewer.

All dashboards cross-link to Loki (`{service_name="social-sentiment"}`) and Tempo (`service.name=social-sentiment`).

---

## CI Pipeline

Triggered by `.github/workflows/social-sentiment.yml` on any change to `social-sentiment/**`.

| Stage | Details |
|---|---|
| **Lint** | `ruff`, dashboard JSON validation, Prometheus rule YAML validation |
| **Test** | Matrix across all 6 test suites with a coverage gate (≥ 70%) |
| **Validate** | Metrics contract, DB schema correctness, keyword config structure |
| **Smoke** | Relevance classifier end-to-end, DB init idempotency |
| **Build** | Docker multi-stage build → push to GHCR |
| **Notify** | Telegram message on successful master deploy |

---

## Running Tests

```bash
cd social-sentiment
pip install pytest pytest-asyncio pytest-cov PyYAML prometheus-client \
    opentelemetry-api opentelemetry-sdk opentelemetry-semantic-conventions pandas

# Run all tests except the Playwright-dependent suite
PYTHONPATH=. OTEL_ENABLED=false SCRAPER_ENABLED_PLATFORMS=reddit BRAND_QUERIES="yeet casino" \
  pytest tests/ -v --ignore=tests/test_scraper_parser.py
```

`test_scraper_parser.py` requires a Chromium installation:

```bash
pip install playwright && playwright install chromium
PYTHONPATH=. pytest tests/test_scraper_parser.py -v
```

With coverage gate (≥ 70%):

```bash
PYTHONPATH=. OTEL_ENABLED=false SCRAPER_ENABLED_PLATFORMS=reddit BRAND_QUERIES="yeet casino" \
  pytest tests/ --cov=. --cov-report=term --cov-fail-under=70
```

To test the sentiment model manually (not included in CI — ~500 MB download):

```bash
PYTHONPATH=. python3 -c "
from nlp.sentiment import SentimentClassifier
c = SentimentClassifier.get(); c.load()
print(c.classify('yeet casino is amazing, fast payouts!'))
"
```

---

## Operational Notes

**First run** — The RoBERTa model downloads on first inference (~500 MB to `MODEL_CACHE_DIR`). It is pre-baked into the Docker image at build time to avoid cold-start delay in production.

**Twitter scraper** — X.com increasingly gates search results behind a login wall. If Reddit alone provides sufficient volume, set `SCRAPER_ENABLED_PLATFORMS=reddit`. The Reddit JSON endpoint is the most stable and reliable source.

**Noise tuning** — Monitor the ratio `social_posts_irrelevant_total / social_posts_collected_total`. If it exceeds 60%, tighten `exclusion_keywords` in `config/keywords.yaml` or lower `RELEVANCE_EMBEDDING_THRESHOLD`.

**Retention** — `purge_old_data()` runs daily at 03:00 UTC inside the scheduler. Raw posts and sentiment results purge after 90 days; alert events after 30 days. Hourly aggregates are retained permanently (negligible row size — never purged).
