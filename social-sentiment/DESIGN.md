# Social Sentiment Subsystem — Implementation Reference

## 1. Final Decision Table

| Component | Selected | Why | Rejected |
|---|---|---|---|
| Scraper runtime | Playwright async | Handles JS-heavy pages; first-class Python async; no external service needed | Selenium (synchronous, heavier), Scrapy (doesn't handle JS), API (costs money or no public access) |
| Browser lib | `playwright.async_api` | Native async, Chromium-only for lean Docker image | Selenium WebDriver (no native async), Puppeteer (Node, wrong stack) |
| Persistence | SQLite + WAL mode | Zero-infra, file-backed, fast for ≤ 10M rows, trivially backedupable | Postgres (overkill for single-writer pipeline), Redis (not relational) |
| Relevance clf | Keyword heuristics + optional sentence-transformer | Deterministic, auditable, zero inference cost; embeddings opt-in for borderline cases | Pure ML classifier (high FP rate on slang, needs labeled training data) |
| Sentiment clf | `cardiffnlp/twitter-roberta-base-sentiment-latest` | Trained on 124M tweets, 3-class (neg/neu/pos), free, ~500MB, CPU-viable | `distilbert-sst2` (binary only), `nlptown/bert-multilingual` (5-star, overkill), VADER (rule-based, poor on casino slang) |
| Embeddings | `all-MiniLM-L6-v2` (opt-in only) | Lightest sentence-transformer (80MB), fast on CPU | `all-mpnet-base-v2` (slower), `text-embedding-ada-002` (costs money) |
| Scheduler | Python `schedule` library (in-process) + cron support | Works in Docker without cron daemon; shell-scriptable for cron environments | Celery (overkill), APScheduler (heavier), raw cron (requires host access) |
| Dashboard integration | Prometheus /metrics endpoint → existing Prometheus scrape | Plugs into existing stack at zero infra cost; Grafana already deployed | Dedicated TSDB, push to Postgres, CloudWatch |
| Alerting | Telegram + Alertmanager dual-path | Telegram: instant free mobile push with zero infra; Alertmanager: integrates with existing Prometheus alert routing and on-call | Slack (requires paid workspace for webhooks in most configs), PagerDuty (paid) |
| Metrics export | `prometheus-client` HTTP server on :9465 | Single file, zero deps beyond prometheus-client, trivially scraped | Pushgateway (adds state, not idiomatic for scheduled jobs here), OTLP metrics push |
| Logging | JSON to stdout → OTEL collector → Loki | Matches existing platform log pipeline exactly; zero additional config | Fluent Bit sidecar, Filebeat |
| Packaging | Multi-stage Dockerfile (base + streamlit target) | Single build context; streamlit variant reuses base without duplicating deps | Separate images (more maintenance), bare Python on host |
| Local deployment | docker-compose service addition | Plugs into existing `docker-compose.yml` without disruption | k3d, separate compose file |

---

## 2. ASCII Architecture Diagram

```
┌───────────────────────────────────────────────────────────────────────┐
│                     Social Sentiment Subsystem                        │
│                                                                       │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────────────────────┐  │
│  │   Scrapers  │   │  Normalizer  │   │    NLP Pipeline           │  │
│  │ ┌─────────┐ │   │              │   │  ┌──────────────────────┐  │  │
│  │ │ Reddit  │─┼──▶│  clean_text  │──▶│  │ RelevanceClassifier  │  │  │
│  │ └─────────┘ │   │  deduplicate │   │  │  (keyword + fuzzy)   │  │  │
│  │ ┌─────────┐ │   │  normalize   │   │  └──────────┬───────────┘  │  │
│  │ │Twitter  │─┘   └──────────────┘   │             │ relevant?    │  │
│  │ └─────────┘                        │             ▼              │  │
│  └─────────────┘                      │  ┌──────────────────────┐  │  │
│         │                             │  │ SentimentClassifier  │  │  │
│         ▼                             │  │  (RoBERTa twitter)   │  │  │
│  ┌─────────────┐                      │  └──────────┬───────────┘  │  │
│  │  SQLite DB  │◀─────────────────────┴─────────────┘              │  │
│  │  raw_posts  │                                                    │  │
│  │  norm_posts │──▶ ┌────────────────────┐                         │  │
│  │  sentiment  │    │ HourlyAggregation  │                         │  │
│  │  hourly_agg │◀───│  pandas/SQL rollup │                         │  │
│  │  alerts     │    └────────┬───────────┘                         │  │
│  └─────────────┘             │                                     │  │
│                              ▼                                     │  │
│                    ┌──────────────────────┐                        │  │
│                    │  Alert Evaluator     │                        │  │
│                    │  neg_ratio threshold │──▶ Telegram            │  │
│                    │  mention spike       │──▶ Alertmanager        │  │
│                    │  scam concern spike  │                        │  │
│                    └──────────────────────┘                        │  │
│                                                                    │  │
│  ┌─────────────────────┐     ┌────────────────────────────────┐   │  │
│  │  Prometheus /metrics│     │  Streamlit Analyst Dashboard   │   │  │
│  │  :9465              │     │  :8501                         │   │  │
│  └──────────┬──────────┘     └────────────────────────────────┘   │  │
│             │                                                      │  │
└─────────────┼──────────────────────────────────────────────────────┘  │
              │                                                          │
              ▼                                                          │
 ┌────────────────────────────────────────────────────────────────────┐ │
 │              EXISTING OBSERVABILITY STACK                          │ │
 │  Prometheus ──▶ Alertmanager ──▶ Telegram / on-call webhook        │ │
 │      │                                                             │ │
 │      ▼                                                             │ │
 │  Grafana  [Brand Intelligence folder]                              │ │
 │  ├── Executive View (KPI stats, 24h sentiment trend)               │ │
 │  ├── Operations View (real-time neg ratio, scraper health, logs)   │ │
 │  └── Pipeline Health (scrape rates, classifier perf, traces)       │ │
 │                                                                    │ │
 │  OTEL Collector ──▶ Tempo (traces)                                 │ │
 │  OTEL Collector ──▶ Loki  (logs)                                   │ │
 └────────────────────────────────────────────────────────────────────┘ │
```

---

## 3. Data Flow

```
[cron / scheduler every 30m]
         │
         ▼
1. scraper.reddit.scrape("y_eet casino", max=100)
   └─▶ HTTP GET reddit.com/search.json (no auth)
   └─▶ yield RawPost(post_id, text, author, score, ...)
         │
         ▼
2. insert_raw_posts() → raw_posts table [UNIQUE(platform, post_id)]
         │
         ▼
3. fetch_unprocessed_raw_posts()
   └─▶ normalize_text(raw_text) → clean_text
   └─▶ insert_normalized_posts() → normalized_posts table
         │
         ▼
4. fetch_unclassified_posts()
   └─▶ BrandRelevanceClassifier.classify_batch(texts)
       └─▶ keyword check → is_relevant, relevance_score, derived_labels
   └─▶ SentimentClassifier.classify_batch(relevant_texts_only)
       └─▶ RoBERTa inference → label, score, raw_pos/neu/neg
   └─▶ upsert_sentiment_results()
         │
         ▼
5. [hourly cron] aggregate_hour(prev_hour, platform, brand_query)
   └─▶ SQL GROUP + pandas → pos/neu/neg counts, ratios, weighted_sentiment
   └─▶ upsert_hourly_aggregate()
         │
         ▼
6. run_alert_evaluation()
   └─▶ evaluate_sentiment_alerts() → NegativeSentimentSpike / Critical
   └─▶ evaluate_mention_spike()    → MentionVolumeSpike
   └─▶ evaluate_no_data_anomaly()  → NoDataAnomaly
   └─▶ evaluate_scraper_health()   → ScrapeFailure
   └─▶ _fire() → insert_alert_event() + send_telegram_alert() + send_alertmanager()
         │
         ▼
7. Prometheus scrapes :9465/metrics every 15s
   └─▶ social_* metrics series written to Prometheus TSDB
   └─▶ Grafana queries series for dashboards
```

---

## 4. Portal Integration Map

```
Grafana Nav (existing)           After this change
─────────────────────────────    ──────────────────────────────────────
├── Platform Health              ├── Platform Health
├── Services                     ├── Services
├── Infrastructure               ├── Infrastructure
├── Reliability                  ├── Reliability
                                 └── Brand Intelligence  ← NEW FOLDER
                                     ├── Executive View
                                     │   └── for: leadership, marketing
                                     │   └── refresh: 5m
                                     │   └── shows: KPI stats, 24h trend
                                     ├── Operations View
                                     │   └── for: on-call, SRE
                                     │   └── refresh: 1m
                                     │   └── shows: real-time ratio, logs, alerts
                                     └── Pipeline Health
                                         └── for: data eng, SRE
                                         └── refresh: 30s
                                         └── shows: scraper perf, traces, classifier

Alertmanager routing:
  domain=brand-intelligence + severity=critical → social-critical receiver
  domain=brand-intelligence + severity=warning  → social-warning receiver
  (Telegram alerts also fire directly from Python service — dual path)

Prometheus rule groups:
  social_sentiment_alerts (new)
  └── SocialNegativeSentimentSpike  (warning)
  └── SocialNegativeSentimentCritical (critical)
  └── SocialScraperFailureRate       (warning)
  └── SocialScraperDown              (critical)
  └── SocialNoDataAnomaly            (warning)
  └── SocialClassifierFailureSpike   (warning)

Loki log queries (in Operations View):
  {service_name="social-sentiment"} | json | level != "debug"
  {service_name="social-sentiment"} | json | msg="alert_fired"

Tempo trace search:
  service.name = "social-sentiment"
  spans: ingest_pipeline, scrape_run, normalize_posts,
         relevance_filter, sentiment_classify, aggregate_hourly,
         evaluate_alerts
```

---

## 5. Rollout Plan

### Day 1 — MVP
1. `docker-compose up social-sentiment` — confirm service starts
2. `python scripts/init_db.py` — verify DB schema
3. Set `BRAND_QUERIES=y_eet casino,y_eet.com` and `SCRAPER_ENABLED_PLATFORMS=reddit`
4. Run `python -m pipeline.ingest` manually — verify posts in DB
5. Confirm `:9465/metrics` returns `social_*` metrics
6. Prometheus scrapes target — confirm in `/targets`
7. Grafana Brand Intelligence folder appears with 3 dashboards

### Week 1 — Stabilization
- Tune `SCRAPER_RATE_LIMIT_DELAY_S` and `SCRAPER_MAX_POSTS_PER_RUN` based on volume
- Monitor noise ratio (posts_irrelevant / posts_collected) — target < 60%
- Add Twitter scraper if public access available; otherwise keep Reddit-only
- Set real `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` for alert delivery
- Tune `ALERT_NEG_RATIO_THRESHOLD` based on baseline (first week data)
- Enable `RELEVANCE_EMBEDDING_ENABLED=true` if borderline FP rate is high

### Week 2 — Observability Hardening
- Verify all Prometheus alert rules fire correctly in staging
- Connect Alertmanager social-critical receiver to real webhook (on-call tool)
- Add Loki-based alert: `count_over_time({service_name="social-sentiment"} |= "alert_fired"[1h]) > 5`
- Add Grafana annotation layer for `social_alerts_triggered_total` changes
- Validate Tempo traces appear for full pipeline run
- Review `social_brand_relevance_confidence_bucket` histogram — tune keyword rules

### Week 3 — Dashboard Refinement
- Add `deep-analysis.json` Grafana dashboard (Loki log panel + raw post drill-down)
- Wire Executive View to Grafana Slack/Teams notification channel for weekly digest
- Add `alert-triage.json` dashboard showing alert history table + Loki correlation
- Share Streamlit dashboard link (`:8501`) with Marketing/CRM team
- Add brand query expansion based on first 2 weeks of collected data
- Set up `purge_old_data()` daily job and verify retention policy
