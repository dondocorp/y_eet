# yeet

> Production-grade iGaming platform — real-time betting, provably fair games, atomic wallets, and full-stack observability. Built to handle money.

---

## What this is

Yeet is a transactional iGaming backend with a complete production observability stack baked in. It's not a demo — every component is wired for real traffic, real money, and real incidents.

**Core platform** — Auth, wallet, bet placement, game sessions, settlement, and fraud/risk, all with idempotent writes and atomic fund management.

**Observability stack** — Distributed traces (Tempo), metrics (Prometheus + Thanos), logs (Loki), dashboards (Grafana), synthetic monitoring (k6 + Blackbox), SLO burn-rate alerting, and Istio mesh telemetry. Everything ships to a single Grafana portal.

---

## Platform Capabilities

### Transactional Core

| Domain | Capability |
|---|---|
| **Auth** | JWT (HS256) + rotating refresh tokens, single-use session invalidation, device fingerprinting |
| **Wallet** | Reserve/release ledger model, idempotent writes, atomic bet staking, zero double-spend |
| **Betting** | 8-step placement pipeline: idempotency → eligibility → limits → session → risk → reserve → persist → settle |
| **Settlement** | Instant (crash/slots via HMAC-SHA256 provably fair) or async settlement via admin/engine |
| **Risk** | Inline rule engine with circuit breaker — high-value bets, velocity, loss limits, account tiers |
| **Game Sessions** | Session lifecycle management, server-seed commitment scheme |
| **Fraud Signals** | Risk signal ingestion and profile scoring (`low → standard → elevated → high → blocked`) |
| **Config Flags** | Runtime feature flag system (`ConfigService`) — enable/disable risk eval, game types, limits |

### Observability Stack

| Signal | Tool | Storage | Retention |
|---|---|---|---|
| **Traces** | OTEL SDK → OTEL Collector (tail sampling) → Tempo | S3 Standard → Glacier IR | 7d hot / 30d cold |
| **Metrics** | Prometheus Operator + Thanos sidecar | S3 (Thanos blocks) | 2d local / 13 months |
| **Logs** | Fluent Bit → Loki (S3 backend) | S3 Standard → Glacier IR | 31d hot / 12m cold |
| **Dashboards** | Grafana OSS 10.x (single portal) | Provisioned from repo | — |
| **Synthetics** | k6 (scripted flows) + Blackbox Exporter | Prometheus metrics | 7d |
| **Mesh telemetry** | Istio Envoy sidecars → Prometheus | Same as metrics | Same as metrics |
| **Alerting** | Prometheus Alertmanager + Grafana Unified | — | — |
| **SLOs** | PromQL recording rules + multi-window burn rate | Same as metrics | — |
| **Long-term** | Thanos Compactor (5m/1h downsampling) | S3 Glacier IR | 13 months |

### Infrastructure

| Concern | Choice |
|---|---|
| **Runtime** | EKS (Kubernetes 1.29+), Karpenter node autoscaling |
| **Service mesh** | Istio 1.21 — mTLS, L7 traffic policy, access logs, tracing |
| **IaC** | Terraform (modular, S3 remote state, OIDC auth) |
| **CI/CD** | GitHub Actions — lint → instrumentation check → observability config validation → test → build → deploy → synthetic validation → SLO regression check |
| **Secrets** | AWS Secrets Manager + IRSA (IAM Roles for Service Accounts) |
| **Container registry** | GitHub Container Registry (GHCR) |

### Reliability Posture

| SLO | Target | Window |
|---|---|---|
| Auth/Session availability | 99.9% | 30d rolling |
| Bet placement availability | 99.5% | 30d rolling |
| Bet placement P99 latency | < 500ms | 30d rolling |
| Wallet read availability | 99.9% | 30d rolling |
| Observability pipeline health | 99.5% | 30d rolling |

---

## Repo Structure

```
yeet/
├── src/                    # Application source (Fastify/TypeScript)
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
│   ├── prometheus/         # PrometheusRules (latency, errors, SLOs, queues, mesh)
│   ├── alertmanager/       # Routing, inhibition, Slack/PagerDuty templates
│   ├── loki/               # Loki config + Fluent Bit DaemonSet
│   ├── tempo/              # Tempo config (S3 + metrics-generator)
│   ├── grafana/            # Dashboard JSON + datasource/folder provisioning
│   ├── k6/                 # Synthetic checks (login, bet placement, post-deploy)
│   ├── synthetic/          # Blackbox Exporter config
│   └── runbooks/           # Incident runbooks (api-outage, queue-lag, wallet, collector, canary)
│
├── terraform/              # Infrastructure provisioning
│   ├── environments/       # prod, staging — root modules
│   └── modules/            # grafana, loki, tempo, prometheus, otel-collector, storage
│
├── .github/workflows/
│   ├── ci.yml              # Lint + instrumentation check + observability validation + tests
│   ├── deploy.yml          # Image build → staging → prod + synthetic gates + SLO check
│   ├── observability-deploy.yml  # Terraform plan/apply + dashboard push + rule deploy
│   └── synthetic-monitoring.yml  # Scheduled k6 checks every 5 minutes
│
└── yeet-synth/             # Python synthetic traffic generator (mesh + chaos scenarios)
```

---

## Quick Start

```bash
# Start the full local stack (API + Postgres + Redis + Prometheus + Loki + Tempo + Grafana)
docker compose up

# API:      http://localhost:8080
# Metrics:  http://localhost:9464/metrics
# Grafana:  http://localhost:3000   (anonymous admin, no login)
# Prometheus: http://localhost:9090
# Tempo:    http://localhost:3200
# Loki:     http://localhost:3100
```

```bash
# Development (hot reload, no observability stack)
cp .env.example .env
npm ci
npm run dev
```

```bash
# Run all checks
npm run lint && npm run typecheck && npm test
```

---

## Key Design Decisions

**Idempotency everywhere** — All mutating endpoints require `Idempotency-Key`. The middleware stores key → response before the handler runs. Retries return the cached response with `X-Idempotency-Replay: true`. Safe to retry; never double-charges.

**Reserve/release wallet model** — Funds move to `reserved` on bet placement, not on settlement. No row-level locks on the hot path. Settlement releases the reserve and credits payout atomically.

**Fail-closed risk** — The circuit breaker's fallback rejects the bet (`decision: reject, score: 100`). A risk service outage never silently allows unscored bets through.

**Trace ID in every response** — All error responses include `trace_id` from the active OTEL span. Frontend can hand this to support; support can paste it into Grafana Tempo and see the full trace.

**No Istio metric duplication** — `yeet_http_requests_total` and `yeet_http_request_duration_ms` are app-layer metrics for route/synthetic context. `istio_requests_total` and `istio_request_duration_milliseconds` are the source of truth for RED metrics and SLOs.

---

## Docs

- [`src/README.md`](src/README.md) — application architecture, service logic, environment variables
- [`observability/README.md`](observability/README.md) — observability platform, telemetry flows, runbook index, dashboard inventory
