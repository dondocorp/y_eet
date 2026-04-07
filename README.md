# Yeet

> Production-grade crypto-casino platform — real-time betting, provably fair games, atomic wallets, full-stack observability, and brand intelligence. Built to handle money.

[![CI](https://github.com/dondocorp/y_eet/actions/workflows/ci.yml/badge.svg)](https://github.com/dondocorp/y_eet/actions/workflows/ci.yml)
[![Deploy](https://github.com/dondocorp/y_eet/actions/workflows/deploy.yml/badge.svg)](https://github.com/dondocorp/y_eet/actions/workflows/deploy.yml)
[![Observability](https://github.com/dondocorp/y_eet/actions/workflows/observability-deploy.yml/badge.svg)](https://github.com/dondocorp/y_eet/actions/workflows/observability-deploy.yml)
![Stack](https://img.shields.io/badge/stack-Node%20%7C%20Python%20%7C%20Postgres%20%7C%20Redis-informational)
![Observability](https://img.shields.io/badge/observability-Prometheus%20%7C%20Grafana%20%7C%20Tempo%20%7C%20Loki-blueviolet)
![IaC](https://img.shields.io/badge/infra-Terraform%20%7C%20EKS%20%7C%20Istio-orange)

---

## Overview

Yeet is a transactional crypto-casino backend with a production-grade observability stack baked in. Every component is wired for real traffic, real money, and real incidents.

| Layer | What it does |
|---|---|
| **Core platform** | Auth, wallet, bet placement, game sessions, settlement, fraud/risk — all idempotent, atomic, and observable |
| **Observability stack** | Distributed traces (Tempo), metrics (Prometheus + Thanos), logs (Loki), dashboards (Grafana), synthetic monitoring, SLO burn-rate alerting, Istio mesh telemetry |
| **Brand intelligence** | Social media sentiment pipeline — Reddit + Twitter scraping, RoBERTa classification, Grafana Brand Intelligence dashboards, Telegram alerts |

---

## Quick Start

**One command. Everything comes alive.**

```bash
./scripts/demo.sh
```

Starts the full stack: API · PostgreSQL · Redis · OTEL Collector · Prometheus · Grafana · Loki · Tempo · Alertmanager · Social Sentiment pipeline · Synthetic traffic. Opens dashboards automatically.

**Prerequisites:** `docker` (Compose v2), `curl`

```bash
./scripts/demo.sh --skip-synth    # no synthetic traffic
./scripts/demo.sh --skip-browser  # skip auto-opening browser
./scripts/demo.sh --rebuild       # force Docker image rebuild
```

> After startup, watch **Grafana → API Reliability** for live request and error rates,  
> **SLO Error Budget** for burn-rate tracking, and **Brand Intelligence** for sentiment signals.

---

## Service Map

| Service | URL | Notes |
|---|---|---|
| API | `http://localhost:8080` | Fastify / TypeScript |
| API metrics | `http://localhost:9464/metrics` | Prometheus scrape endpoint |
| Grafana | `http://localhost:3000` | Anonymous admin — no login |
| Prometheus | `http://localhost:9090` | |
| Alertmanager | `http://localhost:9093` | |
| Tempo | `http://localhost:3200` | Distributed traces |
| Loki | `http://localhost:3100` | Structured logs |
| Sentiment metrics | `http://localhost:9465/metrics` | `social_*` metric family |
| Analyst dashboard | `http://localhost:8501` | Streamlit UI |

---

## Platform Capabilities

### Transactional Core

| Domain | Capability |
|---|---|
| **Auth** | JWT (HS256) + rotating refresh tokens, single-use session invalidation, device fingerprinting |
| **Wallet** | Reserve/release ledger model, idempotent writes, atomic bet staking, zero double-spend |
| **Betting** | 8-step placement pipeline: idempotency → eligibility → limits → session → risk → reserve → persist → settle |
| **Settlement** | Instant (crash/slots via HMAC-SHA256 provably fair) or async via admin/engine |
| **Risk** | Inline rule engine with circuit breaker — high-value bets, velocity, loss limits, account tiers |
| **Game Sessions** | Session lifecycle management, server-seed commitment scheme |
| **Fraud Signals** | Risk signal ingestion and profile scoring (`low → standard → elevated → high → blocked`) |
| **Config Flags** | Runtime feature flag system — enable/disable risk eval, game types, limits |

### Observability Stack

| Signal | Tool | Storage | Retention |
|---|---|---|---|
| **Traces** | OTEL SDK → OTEL Collector (tail sampling) → Tempo | S3 → Glacier IR | 7d hot / 30d cold |
| **Metrics** | Prometheus + Thanos sidecar | S3 (Thanos blocks) | 2d local / 13 months |
| **Logs** | Fluent Bit → Loki (S3 backend) | S3 → Glacier IR | 31d hot / 12m cold |
| **Dashboards** | Grafana OSS 10.x (single portal) | Provisioned from repo | — |
| **Synthetics** | k6 (scripted flows) + Blackbox Exporter | Prometheus metrics | 7d |
| **Mesh telemetry** | Istio Envoy sidecars → Prometheus | Same as metrics | Same as metrics |
| **Alerting** | Prometheus Alertmanager + Grafana Unified | — | — |
| **SLOs** | PromQL recording rules + multi-window burn rate | Same as metrics | — |
| **Long-term** | Thanos Compactor (5m/1h downsampling) | S3 Glacier IR | 13 months |
| **Brand intelligence** | social-sentiment → Prometheus `/metrics` | SQLite (90d raw, permanent hourly) | 90d raw / permanent |

### Brand Intelligence

| Capability | Detail |
|---|---|
| **Sources** | Reddit (JSON + DOM), Twitter/X (public search) |
| **Relevance filtering** | 5-stage keyword pipeline — hard exclusions, primary match, secondary+context, optional embedding gate |
| **Sentiment** | `cardiffnlp/twitter-roberta-base-sentiment-latest` — 3-class (positive / neutral / negative), CPU-only |
| **Derived labels** | `scam_concern`, `payment_issue`, `login_issue`, `ux_praise`, `support_complaint`, `hype` |
| **Aggregation** | Hourly rollup — mention counts, sentiment ratios, influence-weighted score, label frequency |
| **Alerting** | 7 alert rules via Telegram + Alertmanager; suppression + dedup built in |
| **Portal integration** | Brand Intelligence Grafana folder — Executive View, Operations View, Pipeline Health |
| **Analyst UI** | Streamlit on `:8501` — post explorer, top negatives, complaint clusters |

### Infrastructure

| Concern | Choice |
|---|---|
| **Runtime** | EKS (Kubernetes 1.29+), Karpenter node autoscaling |
| **Service mesh** | Istio 1.21 — mTLS, L7 traffic policy, access logs, tracing |
| **IaC** | Terraform (modular, S3 remote state, OIDC auth) |
| **CI/CD** | GitHub Actions — lint → instrumentation check → observability validation → test → build → deploy → synthetic gate → SLO check |
| **Secrets** | AWS Secrets Manager + IRSA |
| **Container registry** | GitHub Container Registry (GHCR) |

### Reliability Posture

| SLO | Target | Window |
|---|---|---|
| Auth / session availability | 99.9% | 30d rolling |
| Bet placement availability | 99.5% | 30d rolling |
| Bet placement P99 latency | < 500ms | 30d rolling |
| Wallet read availability | 99.9% | 30d rolling |
| Observability pipeline health | 99.5% | 30d rolling |

---

## Repo Structure

```
y_eet/
├── src/                    # Application source (Fastify / TypeScript)
│   ├── routes/             # HTTP handlers — auth, wallet, bets, games, risk, health
│   ├── services/           # Business logic — BetService, WalletService, RiskService, …
│   ├── repositories/       # SQL layer — pg pool, typed queries
│   ├── middleware/         # requestId, auth guard, idempotency guard
│   ├── telemetry/          # OTEL SDK init, Prometheus metrics, structured logger
│   └── db/                 # Pool, migration runner, SQL migrations
│
├── observability/          # Full observability platform — infrastructure-as-config
│   ├── collector/          # OTEL Collector configs (DaemonSet + Gateway + local dev)
│   ├── istio/              # Telemetry CRs, PeerAuthentication, mesh config
│   ├── prometheus/         # PrometheusRules (latency, errors, SLOs, queues, mesh, social)
│   ├── alertmanager/       # Routing, inhibition, webhook templates
│   ├── loki/               # Loki config + Fluent Bit DaemonSet
│   ├── tempo/              # Tempo config (S3 + metrics-generator)
│   ├── grafana/            # Dashboard JSON + datasource/folder provisioning
│   │   └── dashboards/
│   │       ├── brand-intelligence/  # Executive View, Operations View, Pipeline Health
│   │       ├── platform-health/
│   │       ├── services/
│   │       ├── infrastructure/
│   │       └── reliability/
│   ├── k6/                 # Synthetic checks (login, bet placement, post-deploy)
│   ├── synthetic/          # Blackbox Exporter config
│   └── runbooks/           # Incident runbooks (api-outage, queue-lag, wallet, collector, canary)
│
├── social-sentiment/       # Brand intelligence pipeline (Python)
│   ├── scraper/            # Playwright scrapers — Reddit, Twitter
│   ├── nlp/                # Relevance classifier, RoBERTa sentiment
│   ├── storage/            # SQLite schema + access layer
│   ├── pipeline/           # Ingest orchestrator, hourly aggregation
│   ├── alerts/             # Alert evaluator, Telegram + Alertmanager sender
│   ├── metrics/            # Prometheus exporter on :9465
│   ├── dashboard/          # Streamlit analyst UI on :8501
│   └── tests/              # Full test suite
│
├── y_eet-synth/             # Python synthetic traffic generator
│   ├── synth/              # Archetypes, profiles, mesh validator, OTel, chaos
│   └── config/             # Profile YAML files
│
├── terraform/              # Infrastructure provisioning
│   ├── environments/       # prod, staging root modules
│   └── modules/            # grafana, loki, tempo, prometheus, otel-collector, storage
│
├── .github/workflows/
│   ├── ci.yml                    # Lint + instrumentation check + tests
│   ├── deploy.yml                # Build → staging → prod + synthetic gates + SLO check
│   ├── observability-deploy.yml  # Terraform + dashboard push + rule deploy
│   ├── synthetic-monitoring.yml  # Scheduled k6 checks every 5 minutes
│   └── social-sentiment.yml      # Sentiment pipeline CI
│
└── scripts/
    └── demo.sh             # One-command local demo launcher
```

---

## Local Development

### Manual stack startup

```bash
cp .env.example .env
docker compose up
```

### API only (no Docker observability)

```bash
cp .env.example .env
npm ci
npm run dev     # hot-reload via ts-node-dev on :8080
```

### Synthetic traffic

```bash
cd y_eet-synth
make install                               # creates .venv, installs deps
make smoke BASE_URL=http://localhost:8080  # 30s smoke test
make run-normal BASE_URL=http://localhost:8080
```

### Run all checks

```bash
npm run lint && npm run typecheck && npm test
```

---

## Key Design Decisions

**Idempotency everywhere** — All mutating endpoints require `Idempotency-Key`. The middleware stores key → response before the handler runs. Retries return the cached response with `X-Idempotency-Replay: true`. Safe to retry; never double-charges.

**Reserve/release wallet model** — Funds move to `reserved` on bet placement, not on settlement. No row-level locks on the hot path. Settlement releases the reserve and credits payout atomically.

**Fail-closed risk** — The circuit breaker's fallback rejects the bet (`decision: reject, score: 100`). A risk service outage never silently allows unscored bets through.

**Trace ID in every response** — All error responses include `trace_id` from the active OTEL span. Frontend hands this to support; support pastes it into Grafana Tempo for the full trace.

**No Istio metric duplication** — `y_eet_http_requests_total` / `y_eet_http_request_duration_ms` are app-layer metrics for route/synthetic context. `istio_requests_total` / `istio_request_duration_milliseconds` are the source of truth for RED metrics and SLOs.

---

## Docs

| Document | What it covers |
|---|---|
| [`observability/README.md`](observability/README.md) | Observability platform, telemetry flows, dashboard inventory, alert rules, SLOs, runbook index |
| [`social-sentiment/README.md`](social-sentiment/README.md) | Brand intelligence pipeline, sentiment model, alert rules, Grafana integration, keyword config |
| [`y_eet-synth/README.md`](y_eet-synth/README.md) | Synthetic traffic generator, traffic profiles, mesh validation, CI integration |





<img width="1932" height="1350" alt="image" src="https://github.com/user-attachments/assets/d9c0680b-553f-4a8a-a4c0-822102c9c9a1" />

