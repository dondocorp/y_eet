# Yeet Platform API — Source Overview

Fastify 4 / TypeScript service powering the Yeet iGaming platform. Handles auth, wallets, bets, game sessions, and real-time risk evaluation.

---

## Architecture

```
src/
├── app.ts               # Fastify app factory (plugins, middleware, routes)
├── server.ts            # Entry point — migrations → listen → graceful shutdown
├── config.ts            # Zod-validated env config (fails fast on bad config)
├── errors.ts            # Typed AppError hierarchy → consistent error shapes
├── routes/              # Thin route handlers — validate input, call services
├── services/            # Business logic (BetService, WalletService, RiskService, …)
├── repositories/        # DB access layer (pg pool, idempotency store)
├── middleware/          # requestId, auth guard, idempotency guard
├── telemetry/           # OTel tracer init + named metric counters/histograms
└── db/                  # Connection pool, migration runner, SQL migrations
```

The stack follows a strict **Route → Service → Repository** layering. Services own all business rules; repositories own all SQL; routes own nothing except schema validation and HTTP concerns.

---

## Core Logic

### Bet Placement (`BetService.placeBet`)
An 8-step pipeline executed on every bet:

1. **Idempotency check** — returns the cached result if the key was already processed
2. **User eligibility** — active status + KYC verified
3. **Bet limits** — stake validated against user-configured daily limits
4. **Game session validation** — session must be active and owned by the requesting user
5. **Risk evaluation** — async score computed via `RiskService` (circuit-breaker protected, 80ms timeout)
6. **Fund reservation** — debit from wallet into a reserved balance (atomic, idempotent)
7. **Bet record creation** — persisted with risk score, decision, and wallet tx reference
8. **Instant settlement** — crash and slots games settle immediately using a deterministic HMAC-SHA256 outcome

### Wallet (`WalletService`)
Uses a **reserve/release** model: funds are moved to a `reserved` balance on bet placement and released on settlement. This prevents double-spend without row locks on hot paths. All writes carry idempotency keys so retries are safe.

### Risk Engine (`RiskService`)
Inline rule engine with four signals: high-value single bet (≥$1000), rapid bet velocity (>30 bets/60s), approaching daily loss limit (>80%), and account tier block. Score maps to tiers (`low → standard → elevated → high → blocked`). Scores ≥80 reject; scores ≥60 flag for review.

### Idempotency Middleware
`idempotencyGuard()` is a per-route `preHandler`. On first request: stores key → runs handler → `onSend` hook persists the response. On replay: returns the cached status + body immediately with `X-Idempotency-Replay: true`. Non-fatal if the store is unavailable.

---

## SRE Properties

### Observability
- **Distributed tracing** — OTel SDK initialized before all `require()` calls (`telemetry/tracer.ts`), auto-instrumenting pg, HTTP, and Node core. Traces exported via OTLP gRPC.
- **Metrics** — Prometheus scrape endpoint on a dedicated port (`PROMETHEUS_PORT`, default `9464`). Named metrics cover every critical path: `yeet_bet_placement_duration_ms`, `yeet_betting_volume_usd_total`, `yeet_risk_eval_duration_ms`, `yeet_wallet_transfers_total`, `yeet_idempotency_hits_total`, and more.
- **Structured logging** — Pino JSON logs. Every log line carries `request_id`, `method`, `url`, and a `synthetic` flag (driven by `X-Synthetic: true` header) so synthetic canary traffic is filterable in log queries without code changes.

### Resilience
- **Circuit breaker on risk** — `opossum` wraps the risk evaluation function. Opens after 30% error rate over 5 samples, resets after 15s. Fail-closed: when open, bets are rejected rather than allowed through unscored.
- **30s request timeout** — hard ceiling enforced at the Fastify level; prevents runaway DB queries from holding connections.
- **Graceful shutdown** — `SIGTERM`/`SIGINT` drain the PG pool before exit. `unhandledRejection` exits with code 1 to trigger a container restart rather than running in a degraded state.
- **Idempotent retries** — all mutating endpoints (`POST /wallet/*`, `POST /bets`) require an `Idempotency-Key` header, making client retries safe with zero duplicate side-effects.

### Health Endpoints (`/health/*`)
| Endpoint | Purpose | Used by |
|---|---|---|
| `/health/live` | Process alive | Kubernetes liveness probe |
| `/health/ready` | DB reachable | Kubernetes readiness probe |
| `/health/startup` | One-time DB check | Kubernetes startup probe |
| `/health/dependencies` | Latency per dependency | Dashboards / on-call runbooks |

### Rate Limiting
Per-user (by JWT `sub`) when authenticated, per-IP otherwise. Configurable via `RATE_LIMIT_MAX` / `RATE_LIMIT_WINDOW_MS`. Returns `retry_after_ms` in the error body for client back-off.

### Config Safety
All environment variables are parsed and validated by Zod at startup (`config.ts`). Invalid config prints a field-level error and exits with code 1 — the service will never start in a misconfigured state.

### Migrations
`runMigrations()` executes before the server starts accepting traffic, ensuring schema and code are always in sync on deploy with no manual intervention required.

---

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgres://yeet:yeet@localhost:5432/yeet` | |
| `JWT_SECRET` | *(dev placeholder)* | Must be ≥32 chars in production |
| `JWT_EXPIRY` | `15m` | Short-lived; pair with refresh tokens |
| `REDIS_URL` | *(optional)* | Used by idempotency store when set |
| `RATE_LIMIT_MAX` | `100` | Requests per window |
| `RATE_LIMIT_WINDOW_MS` | `60000` | 1 minute |
| `RISK_EVAL_TIMEOUT_MS` | `80` | Circuit breaker timeout |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | Trace collector |
| `PROMETHEUS_PORT` | `9464` | Metrics scrape port |
| `LOG_LEVEL` | `info` | `trace\|debug\|info\|warn\|error\|silent` |
