# Platform API

> Fastify 4 / TypeScript service powering auth, wallets, bet placement, game sessions,
> risk evaluation, and fraud signal ingestion. Every money operation is idempotent,
> atomically safe, and fully instrumented.

---

## Architecture

The codebase enforces a strict three-layer model — no exceptions:

| Layer | Responsibility | What it must not do |
|---|---|---|
| **Routes** | Parse HTTP requests, validate input, shape HTTP responses | Contain business logic or SQL |
| **Services** | All business logic, rules, and orchestration | Execute SQL directly |
| **Repositories** | All SQL queries, typed results | Contain business logic |

---

## Directory Structure

```
src/
├── app.ts                   # Fastify factory — plugins, middleware, routes, error handler
├── server.ts                # Entry point — run migrations → start server → graceful shutdown
├── config.ts                # Zod-validated env config — exits immediately on misconfiguration
├── errors.ts                # Typed AppError hierarchy → consistent JSON error shapes
│
├── routes/                  # Thin HTTP handlers — one directory per domain
│   ├── auth/                # POST /login, /register, /refresh, /logout
│   ├── bets/                # POST /place, /settle, /void — GET /history, /:id
│   ├── wallet/              # GET /balance — POST /deposit, /withdraw, /transactions
│   ├── games/               # Game session lifecycle
│   ├── risk/                # Risk score reads, signal ingestion
│   ├── users/               # User profile, KYC status, limits
│   ├── config/              # Feature flags
│   ├── admin/               # Internal ops (admin-only)
│   └── health/              # /live, /ready, /startup, /dependencies
│
├── services/                # All business logic
│   ├── AuthService.ts       # Login, register, token rotation, session validation
│   ├── BetService.ts        # 8-step bet placement pipeline + settlement
│   ├── WalletService.ts     # Reserve/release ledger operations
│   ├── RiskService.ts       # Inline rule engine + circuit breaker
│   ├── GameSessionService.ts # Session lifecycle + seed commitment
│   └── ConfigService.ts     # Runtime feature flags
│
├── repositories/            # All SQL — no business logic
│   ├── BetRepository.ts
│   ├── WalletRepository.ts
│   ├── UserRepository.ts
│   ├── RiskRepository.ts
│   ├── GameSessionRepository.ts
│   ├── IdempotencyRepository.ts
│   └── ConfigRepository.ts
│
├── middleware/
│   ├── requestId.ts         # Propagates X-Request-ID, records HTTP metrics, flags synthetic traffic
│   ├── auth.ts              # requireAuth + requireRole guards
│   └── idempotency.ts       # idempotencyGuard — store-before-execute, replay on duplicate
│
├── telemetry/
│   ├── tracer.ts            # OTEL SDK init — must be the first import in server.ts
│   ├── metrics.ts           # All named metric instruments (counters, histograms, gauges)
│   └── logger.ts            # Pino JSON logger with live OTEL trace_id/span_id injection
│
└── db/
    ├── pool.ts              # pg Pool singleton + connection health check
    ├── migrate.ts           # Migration runner (sequential, blocking on startup)
    └── migrations/          # Numbered SQL files — 001_initial, 002_seed, …
```

---

## Core Service Logic

### `BetService.placeBet` — 8-Step Pipeline

Every bet placement runs these steps in order, short-circuiting on failure at each gate:

| Step | Gate | Purpose |
|---|---|---|
| 1 | **Idempotency check** | Returns cached result if the key was already processed — safe for client retries |
| 2 | **User eligibility** | Active status + KYC verified — hard gate before any funds move |
| 3 | **Bet limits** | Stake vs. user-configured daily limit — regulatory requirement |
| 4 | **Session validation** | Active session owned by this user — anti-replay |
| 5 | **Risk evaluation** | Score via `RiskService` (80ms timeout, circuit-breaker protected) |
| 6 | **Fund reservation** | Debit from `available` → `reserved` balance (atomic, idempotent) |
| 7 | **Bet record creation** | Persisted with risk score, decision, and wallet transaction reference |
| 8 | **Instant settlement** | Crash/slots games settle immediately via deterministic HMAC-SHA256 |

The full flow is wrapped in a `tracer.startActiveSpan('bet.place')` span with attributes: `bet.id`, `bet.risk_score`, `bet.risk_decision`, `bet.duration_ms`, `bet.idempotency_hit`.

### `WalletService` — Reserve/Release Model

Funds move through three states:

```
available  →  reserved  →  released   (win: reserve cleared, payout credited to available)
                        →  forfeited  (loss: reserve cleared, no credit)
                        →  voided     (void: reserve returned to available)
```

Every operation carries an idempotency key derived from the bet ID. Concurrent retries are safe; concurrent double-executions are impossible.

### `RiskService` — Inline Rule Engine

Four signals evaluated synchronously on every bet:

| Signal | Threshold | Score contribution |
|---|---|---|
| High-value single bet | ≥ $1,000 | +20 |
| Rapid velocity | > 30 bets in 60s | +30 |
| Approaching daily loss limit | > 80% of limit | +10 |
| Account tier blocked | `riskTier === 'blocked'` | → 100 (hard reject) |

| Score range | Tier | Decision |
|---|---|---|
| < 20 | `low` | allow |
| 20–39 | `standard` | allow |
| 40–59 | `elevated` | allow |
| 60–79 | `high` | review |
| ≥ 80 | `blocked` | reject |

The circuit breaker (opossum) opens at 30% error rate over 5 samples and resets after 15 seconds. **Fail-closed** — an open circuit rejects the bet with `score: 100, decision: reject`. A risk service outage never silently passes unscored bets through.

### `AuthService` — Token Rotation

- **Access tokens** — HS256, 15-minute expiry, carries `sub`, `sessionId`, `roles`, `riskTier`
- **Refresh tokens** — hashed (`bcrypt`, rounds=10) and stored in the `sessions` table
- **Single-use rotation** — consuming a refresh token marks it `used_at`; reuse returns 401
- **Session revocation** — `revoked_at` timestamp is checked on every token refresh

---

## Telemetry Contracts

### Metrics (`telemetry/metrics.ts`)

All instruments follow the naming convention `y_eet_{domain}_{operation}_{unit}`.

| Instrument | Type | Labels |
|---|---|---|
| `y_eet_auth_tokens_issued_total` | Counter | `type` |
| `y_eet_auth_failures_total` | Counter | `reason` |
| `y_eet_bet_placements_total` | Counter | `status`, `game_id` |
| `y_eet_bet_placement_duration_ms` | Histogram | — |
| `y_eet_bet_settlements_total` | Counter | `outcome`, `game_id` |
| `y_eet_bet_settlement_duration_ms` | Histogram | — |
| `y_eet_betting_volume_usd_total` | Counter | `game_id` |
| `y_eet_wallet_transfers_total` | Counter | `type`, `status` |
| `y_eet_wallet_transfer_duration_ms` | Histogram | — |
| `y_eet_risk_evaluations_total` | Counter | `decision` |
| `y_eet_risk_eval_duration_ms` | Histogram | — |
| `y_eet_risk_circuit_breaker_open_total` | Counter | — |
| `y_eet_active_game_sessions` | ObservableGauge | — |
| `y_eet_idempotency_hits_total` | Counter | — |
| `y_eet_http_requests_total` | Counter | `method`, `route`, `status`, `synthetic` |
| `y_eet_http_request_duration_ms` | Histogram | `method`, `route`, `status`, `synthetic` |

> `y_eet_http_*` metrics serve route-level and synthetic-context use cases. Use `istio_requests_total` and `istio_request_duration_milliseconds` for RED metrics and SLO calculations.

### Traces (`telemetry/tracer.ts`)

The OTEL SDK is initialized before all other imports and auto-instruments HTTP, pg, and Node core.

Key spans:

- **`bet.place`** — full placement pipeline; attributes: `bet.game_id`, `bet.amount_usd`, `bet.risk_score`, `bet.risk_decision`, `bet.id`, `bet.duration_ms`
- HTTP spans are suppressed for `/health/*` and `/metrics` paths
- `db.*` spans from pg auto-instrumentation include `db.statement` (redacted in production by a collector processor)

All spans carry resource attributes: `service.name`, `service.version`, `deployment.environment`, `k8s.cluster.name`, `k8s.namespace.name`, `k8s.pod.name`, `k8s.node.name`.

### Logs (`telemetry/logger.ts`)

Pino JSON logger. Every line includes `trace_id` and `span_id` from the active OTEL context, making logs directly correlatable with Tempo traces in Grafana. Fastify's built-in logger injects trace context on all request lifecycle events via the `mixin` option in `app.ts`.

Error responses always include `trace_id` — clients can pass this to support for exact trace lookup.

### Synthetic Traffic Tagging

Requests with `X-Synthetic: true` set `request.isSynthetic = true`. This propagates into:

- HTTP metric labels (`synthetic: "true"`) — filterable in Grafana
- Fastify request serializer log field — filterable in Loki
- Istio Telemetry CR custom tag (`synthetic.check`) — triggers 100% trace sampling for synthetic requests

---

## Middleware

### `idempotencyGuard(namespace, path)`

A `preHandler` hook. On first request: stores key → executes handler → `onSend` hook persists response body and status. On replay: returns the cached response immediately with `X-Idempotency-Replay: true`. If the store is unavailable, requests proceed without idempotency protection (logged as a warning — non-fatal by design).

### `registerRequestMiddleware(fastify)`

Registered once on the root Fastify instance. Propagates or generates `X-Request-ID`, sets `request.isSynthetic`, records HTTP metrics on every response, and echoes `X-Service-Version` and `X-Request-ID` back in response headers.

---

## Health Endpoints

| Endpoint | Condition | Kubernetes probe |
|---|---|---|
| `GET /health/live` | Process is running | Liveness |
| `GET /health/ready` | Database is reachable | Readiness |
| `GET /health/startup` | Database is reachable (checked once) | Startup |
| `GET /health/dependencies` | Database latency breakdown | Dashboards / runbooks |

---

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgres://y_eet:y_eet@localhost:5432/y_eet` | |
| `JWT_SECRET` | *(dev placeholder)* | Must be ≥ 32 characters in production |
| `JWT_EXPIRY` | `15m` | Use with refresh tokens |
| `REFRESH_TOKEN_EXPIRY_DAYS` | `7` | |
| `BCRYPT_ROUNDS` | `12` | Lower in tests (`8`) for speed |
| `RATE_LIMIT_MAX` | `100` | Requests per window |
| `RATE_LIMIT_WINDOW_MS` | `60000` | 1 minute |
| `RISK_EVAL_TIMEOUT_MS` | `80` | Circuit breaker opens at this threshold |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTEL Collector gRPC endpoint |
| `PROMETHEUS_PORT` | `9464` | Metrics scrape port (separate from app port) |
| `LOG_LEVEL` | `info` | `trace \| debug \| info \| warn \| error \| silent` |
| `K8S_CLUSTER_NAME` | `local` | Injected via Downward API in Kubernetes |
| `K8S_NAMESPACE` | `local` | Injected via Downward API |
| `K8S_POD_NAME` | `local` | Injected via Downward API |
| `K8S_NODE_NAME` | `local` | Injected via Downward API |
