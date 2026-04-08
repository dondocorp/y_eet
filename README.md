# Yeet Platform

> Production-grade crypto-casino backend — real-time betting, provably fair games, atomic wallets,
> full-stack observability, and brand intelligence. Built to handle money.

[![CI](https://github.com/dondocorp/yeet/actions/workflows/ci.yml/badge.svg)](https://github.com/dondocorp/yeet/actions/workflows/ci.yml)
[![Deploy](https://github.com/dondocorp/yeet/actions/workflows/deploy.yml/badge.svg)](https://github.com/dondocorp/yeet/actions/workflows/deploy.yml)
[![Observability](https://github.com/dondocorp/yeet/actions/workflows/observability-deploy.yml/badge.svg)](https://github.com/dondocorp/yeet/actions/workflows/observability-deploy.yml)
![Stack](https://img.shields.io/badge/stack-Node%20%7C%20Go%20%7C%20Python%20%7C%20Postgres%20%7C%20Redis-informational)
![Observability](https://img.shields.io/badge/observability-Prometheus%20%7C%20Grafana%20%7C%20Tempo%20%7C%20Loki-blueviolet)
![IaC](https://img.shields.io/badge/infra-Terraform%20%7C%20EKS%20%7C%20Istio-orange)

---

## Challenge Coverage

> **Full requirement-by-requirement breakdown → [CHALLENGE_STATUS.md](CHALLENGE_STATUS.md)**

**95% of stated JD requirements covered** (21 of 22 line items across tech stack, key responsibilities, and required skills). The only gap is CDK/CloudFormation — Terraform is used exclusively for IaC. GitLab CI is substituted with GitHub Actions on an identical pipeline model; a drop-in GitLab equivalent is documented in [`y_eet-synth/README.md`](y_eet-synth/README.md).

**7 features delivered beyond spec:**

| Extra | Description |
|---|---|
| Brand Intelligence pipeline | Python NLP subsystem — Reddit/Twitter scraping, RoBERTa sentiment classification, 13 Prometheus metrics, 3 Grafana dashboards, 7 Telegram alert rules, Streamlit analyst UI |
| `y_eet-synth` Go CLI | Synthetic traffic generator and Istio mesh validator — 9 load profiles, 8 CLI commands, chaos fault injection, canary split validation, structured JSON reports |
| Thanos long-term storage | 13-month metric retention with 5m/1h downsampling on S3 + Glacier IR |
| Istio service mesh | mTLS STRICT mode, L7 traffic policy, circuit breaker, canary weight validation, fault injection |
| Multi-window SLO burn-rate alerting | Fast burn (1h / 14.4×) + slow burn (6h / 6×) across all 5 SLOs |
| Provably fair gaming | HMAC-SHA256 server-seed commitment scheme for crash and slots |
| Reserve/release wallet model | Atomic bet staking with no hot-path row locks and zero double-spend guarantee |

**Conservative effort estimate:** ~22,500 lines of authored code across 7 languages (TypeScript 5,585 · Python 4,451 · Go 3,799 · YAML 4,074 · JSON 2,910 · Shell 1,075 · Terraform 568). At a senior-engineer pace of ~150 production lines per hour, that is roughly **150 hours / 4 weeks** of focused work — before accounting for architecture design, debugging, and domain research across crypto-casino compliance, NLP pipelines, and Istio internals.

---

## Architecture

Three distinct subsystems, all sharing the same observability stack:

| Subsystem | Language | What it does |
|---|---|---|
| **Platform API** | TypeScript / Fastify | Auth, wallet, bet placement, game sessions, settlement, fraud/risk — idempotent, atomic, fully instrumented |
| **Observability Platform** | YAML / Terraform / JSON | Distributed traces, metrics, logs, dashboards, SLOs, synthetic monitoring, Istio mesh telemetry |
| **Brand Intelligence** | Python | Social media scraping, NLP sentiment classification, Prometheus metrics, Grafana dashboards, Telegram alerts |

The Go **`y_eet-synth`** tool drives synthetic traffic against the API, validates Istio mesh policies, injects chaos faults, and acts as a CI gate for deployments.

---

## Quick Start

**One command starts the entire stack.**

```bash
./scripts/demo.sh
```

This launches: API · PostgreSQL · Redis · OTEL Collector · Prometheus · Grafana · Loki · Tempo · Alertmanager · Social Sentiment pipeline · Synthetic traffic. Grafana opens automatically.

**Prerequisites:** `docker` (Compose v2), `curl`, `go` 1.21+

```bash
./scripts/demo.sh --skip-synth    # skip synthetic traffic generation
./scripts/demo.sh --skip-browser  # don't auto-open Grafana
./scripts/demo.sh --rebuild       # force Docker image rebuilds
```

> After startup, navigate to **Grafana → API Reliability** for live request rates and error tracking, **SLO Error Budget** for burn-rate visibility, and **Brand Intelligence** for real-time sentiment signals.

---

## Local Service Map

| Service | URL | Notes |
|---|---|---|
| API | `http://localhost:8080` | Fastify / TypeScript |
| API metrics | `http://localhost:9464/metrics` | Prometheus scrape target |
| Grafana | `http://localhost:3000` | Anonymous admin — no login required |
| Prometheus | `http://localhost:9090` | |
| Alertmanager | `http://localhost:9093` | |
| Tempo | `http://localhost:3200` | Distributed trace storage |
| Loki | `http://localhost:3100` | Structured log storage |
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
| **Risk** | Inline rule engine with circuit breaker — velocity, loss limits, value thresholds, account tiers |
| **Game Sessions** | Session lifecycle management with server-seed commitment scheme |
| **Fraud Signals** | Risk signal ingestion and profile scoring (`low → standard → elevated → high → blocked`) |
| **Config Flags** | Runtime feature flag system — enable/disable risk eval, game types, limits |

### Observability Stack

| Signal | Tool | Storage | Retention |
|---|---|---|---|
| **Traces** | OTEL SDK → Collector (tail sampling) → Tempo | S3 → Glacier IR | 7d hot / 30d cold |
| **Metrics** | Prometheus + Thanos | S3 Thanos blocks | 2d local / 13 months |
| **Logs** | Fluent Bit → Loki | S3 → Glacier IR | 31d hot / 12 months |
| **Dashboards** | Grafana OSS 10.x | Provisioned from repo | — |
| **Synthetics** | k6 scripted flows + Blackbox Exporter | Prometheus metrics | 7d |
| **Mesh telemetry** | Istio Envoy sidecars → Prometheus | Same as metrics | Same as metrics |
| **Alerting** | Prometheus Alertmanager + Grafana Unified Alerting | — | — |
| **SLOs** | PromQL recording rules + multi-window burn rate | Same as metrics | — |
| **Long-term storage** | Thanos Compactor (5m / 1h downsampling) | S3 Glacier IR | 13 months |
| **Brand intelligence** | social-sentiment → Prometheus `/metrics` | SQLite (90d raw / permanent hourly) | — |

### Brand Intelligence

| Capability | Detail |
|---|---|
| **Sources** | Reddit (JSON + DOM fallback), Twitter/X (public search) |
| **Relevance filtering** | 5-stage keyword pipeline — hard exclusions, primary match, secondary + context, optional embedding gate |
| **Sentiment** | `cardiffnlp/twitter-roberta-base-sentiment-latest` — 3-class (positive / neutral / negative), CPU-only |
| **Derived labels** | `scam_concern`, `payment_issue`, `login_issue`, `ux_praise`, `support_complaint`, `hype` |
| **Aggregation** | Hourly rollup — mention counts, sentiment ratios, influence-weighted score, label frequency |
| **Alerting** | 7 alert rules via Telegram + Alertmanager; suppression and dedup built in |
| **Dashboards** | Brand Intelligence Grafana folder — Executive View, Operations View, Pipeline Health |
| **Analyst UI** | Streamlit on `:8501` — post explorer, top negatives, complaint clusters |

### Infrastructure

| Concern | Choice |
|---|---|
| **Runtime** | EKS (Kubernetes 1.29+) with Karpenter node autoscaling |
| **Service mesh** | Istio 1.21 — mTLS, L7 traffic policy, access logs, distributed tracing |
| **IaC** | Terraform — modular, S3 remote state, OIDC auth |
| **CI/CD** | GitHub Actions — lint → instrumentation check → observability validation → test → build → deploy → synthetic gate → SLO check |
| **Secrets** | AWS Secrets Manager + IRSA (no static credentials in pod specs) |
| **Container registry** | GitHub Container Registry (GHCR) |

### SLOs

| SLO | Target | Window |
|---|---|---|
| Auth / session availability | 99.9% | 30d rolling |
| Bet placement availability | 99.5% | 30d rolling |
| Bet placement P99 latency | < 500ms | 30d rolling |
| Wallet read availability | 99.9% | 30d rolling |
| Observability pipeline health | 99.5% | 30d rolling |

---

## Repository Structure

```
yeet/
├── src/                         # Platform API (Fastify / TypeScript)
│   ├── routes/                  # HTTP handlers — auth, wallet, bets, games, risk, health
│   ├── services/                # Business logic — BetService, WalletService, RiskService, …
│   ├── repositories/            # SQL layer — typed queries, no business logic
│   ├── middleware/              # requestId, auth guard, idempotency guard
│   ├── telemetry/               # OTEL SDK init, Prometheus metrics, structured logger
│   └── db/                      # Connection pool, migration runner, SQL migrations
│
├── observability/               # Full observability platform — infrastructure-as-config
│   ├── collector/               # OTEL Collector configs (DaemonSet + Gateway + local dev)
│   ├── istio/                   # Telemetry CRs, PeerAuthentication, mesh config
│   ├── prometheus/              # PrometheusRules (latency, errors, SLOs, queues, mesh, social)
│   ├── alertmanager/            # Routing, inhibition, Slack/PagerDuty webhook templates
│   ├── loki/                    # Loki config + Fluent Bit DaemonSet
│   ├── tempo/                   # Tempo config (S3 + metrics-generator)
│   ├── grafana/                 # Dashboard JSON + datasource/folder provisioning
│   │   └── dashboards/
│   │       ├── brand-intelligence/   # Executive View, Operations View, Pipeline Health
│   │       ├── platform-health/      # Executive Health, Global Overview, SLO Error Budget
│   │       ├── services/             # API Reliability, Auth, Wallet, Betting, Games, Risk
│   │       ├── infrastructure/       # Istio, Queue, Infra/Runtime, AWS Managed Services
│   │       └── reliability/          # Incident Triage, Deployment Health, Synthetic Monitoring
│   ├── k6/                      # Synthetic checks (login flow, bet placement, post-deploy)
│   ├── synthetic/               # Blackbox Exporter config
│   └── runbooks/                # Incident runbooks — api-outage, queue-lag, wallet, collector, canary
│
├── social-sentiment/            # Brand Intelligence pipeline (Python)
│   ├── scraper/                 # Playwright scrapers — Reddit, Twitter
│   ├── nlp/                     # Relevance classifier, RoBERTa sentiment
│   ├── storage/                 # SQLite schema + access layer
│   ├── pipeline/                # Ingest orchestrator, hourly aggregation
│   ├── alerts/                  # Alert evaluator, Telegram + Alertmanager sender
│   ├── metrics/                 # Prometheus exporter on :9465
│   ├── dashboard/               # Streamlit analyst UI on :8501
│   ├── scripts/                 # scheduler.py, seed_demo.py, test_fetch.py, init_db.py
│   └── tests/                   # 6 test suites (≥ 70% coverage gate)
│
├── y_eet-synth/                 # Go synthetic traffic generator and mesh validator
│   ├── main.go                  # CLI entrypoint (cobra)
│   ├── internal/                # config, client, metrics, token, scenarios, runner,
│   │                            # mesh, chaos, evaluator, reporter
│   └── config/                  # Profile YAML overrides
│
├── terraform/                   # Infrastructure provisioning
│   ├── environments/            # prod and staging root modules
│   └── modules/                 # grafana, loki, tempo, prometheus, otel-collector, storage
│
├── .github/workflows/
│   ├── ci.yml                   # Lint + instrumentation check + observability validation + tests
│   ├── deploy.yml               # Build → staging → prod + synthetic gates + SLO check
│   ├── observability-deploy.yml # Terraform + dashboard push + PrometheusRules + Istio CRD apply
│   ├── synthetic-monitoring.yml # Scheduled synthetic checks every 5 minutes
│   └── social-sentiment.yml     # Brand intelligence pipeline CI
│
└── scripts/
    └── demo.sh                  # One-command local demo launcher
```

---

## Local Development

### Full stack

```bash
cp .env.example .env
docker compose up
```

### API only

```bash
cp .env.example .env
npm ci
npm run dev        # hot-reload via ts-node-dev on :8080
```

### Run checks

```bash
npm run lint && npm run typecheck && npm test
```

### Synthetic traffic

```bash
cd y_eet-synth
go build -o y_eet-synth .

make smoke       BASE_URL=http://localhost:8080   # 30s smoke test
make run-normal  BASE_URL=http://localhost:8080   # standard production profile
make run-mesh    BASE_URL=http://localhost:8080   # Istio mesh validation
```

---

## Design Decisions

**Idempotency everywhere.** All mutating endpoints require an `Idempotency-Key` header. The middleware stores key → response before the handler executes. Duplicate requests return the cached response immediately with `X-Idempotency-Replay: true`. Safe to retry; never double-charges.

**Reserve/release wallet model.** Funds move from `available` to `reserved` on bet placement — not on settlement. No row-level locks on the hot path. Settlement atomically releases the reserve and credits the payout or clears the loss.

**Fail-closed risk engine.** The circuit breaker's fallback rejects the bet with `decision: reject, score: 100`. A risk service outage never silently allows unscored bets through.

**Trace ID in every error response.** Clients receive the `trace_id` of the active OTEL span on any error. Support pastes it directly into Grafana Tempo for the full distributed trace.

**No Istio metric duplication.** `y_eet_http_*` metrics serve route-level and synthetic-context use cases. `istio_requests_total` and `istio_request_duration_milliseconds` are the authoritative source for RED metrics and SLO calculations.

---

## Documentation

| Document | Contents |
|---|---|
| [`src/README.md`](src/README.md) | API architecture, service logic, telemetry contracts, middleware, environment variables |
| [`observability/README.md`](observability/README.md) | Observability platform, telemetry flows, dashboard inventory, alert rules, SLOs, runbooks |
| [`social-sentiment/README.md`](social-sentiment/README.md) | Brand Intelligence pipeline, NLP model, alert rules, Grafana integration, keyword config |
| [`y_eet-synth/README.md`](y_eet-synth/README.md) | Go synthetic tool — build, CLI reference, traffic profiles, mesh validation, chaos, CI integration |
| [`CHALLENGE_STATUS.md`](CHALLENGE_STATUS.md) | Requirement-by-requirement coverage map against the JD |

---

<img width="1932" height="1350" alt="Grafana dashboard screenshot" src="https://github.com/user-attachments/assets/d9c0680b-553f-4a8a-a4c0-822102c9c9a1" />
