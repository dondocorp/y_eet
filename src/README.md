# Platform API — Source

> Fastify 4 / TypeScript service. Auth, wallets, bets, game sessions, risk evaluation, and fraud signal ingestion. All money operations are idempotent and atomically safe.

---

## Structure

```
src/
├── app.ts               # Fastify factory — plugins, middleware, routes, error handler
├── server.ts            # Entry point — run migrations → start server → graceful shutdown
├── config.ts            # Zod-validated env config — exits immediately on bad config
├── errors.ts            # Typed AppError hierarchy → consistent JSON error shapes
│
├── routes/              # Thin HTTP handlers — validate input, delegate to services
│   ├── auth/            # POST /login, /register, /refresh, /logout
│   ├── bets/            # POST /place, /settle, /void — GET /history, /:id
│   ├── wallet/          # GET /balance — POST /deposit, /withdraw, /transactions
│   ├── games/           # Game session lifecycle
│   ├── risk/            # Risk score reads, signal ingestion
│   ├── users/           # User profile, KYC status, limits
│   ├── config/          # Feature flags
│   ├── admin/           # Internal ops (admin-only)
│   └── health/          # /live, /ready, /startup, /dependencies
│
├── services/            # All business logic lives here
│   ├── AuthService.ts          # Login, register, token rotation, session validation
│   ├── BetService.ts           # 8-step bet placement pipeline + settlement
│   ├── WalletService.ts        # Reserve/release ledger operations
│   ├── RiskService.ts          # Inline rule engine + circuit breaker
│   ├── GameSessionService.ts   # Session lifecycle + seed commitment
│   └── ConfigService.ts        # Runtime feature flags
│
├── repositories/        # All SQL lives here — no business logic
│   ├── BetRepository.ts
│   ├── WalletRepository.ts
│   ├── UserRepository.ts
│   ├── RiskRepository.ts
│   ├── GameSessionRepository.ts
│   ├── IdempotencyRepository.ts
│   └── ConfigRepository.ts
│
├── middleware/
│   ├── requestId.ts     # Propagates X-Request-ID, records HTTP metrics, flags synthetic traffic
│   ├── auth.ts          # requireAuth + requireRole guards
│   └── idempotency.ts   # idempotencyGuard — store-before-execute, replay on duplicate
│
├── telemetry/
│   ├── tracer.ts        # OTEL SDK init — must be first import in server.ts
│   ├── metrics.ts       # All named metric instruments (counters, histograms, gauges)
│   └── logger.ts        # Pino logger with live OTEL trace_id/span_id injection
│
└── db/
    ├── pool.ts          # pg Pool singleton + connection health check
    ├── migrate.ts       # Migration runner (sequential, blocking on startup)
    └── migrations/      # Numbered SQL files — 001_initial, 002_seed, …
```

The stack enforces strict **Route → Service → Repository** layering:
- **Routes** — request parsing and HTTP response shaping only
- **Services** — all business logic and rules
- **Repositories** — all SQL, no business logic

---

## Service Logic

### `BetService.placeBet` — 8-step pipeline

Every bet placement executes these steps in order, short-circuiting on failure at each gate:

| Step | What | Why |
|---|---|---|
| 1 | **Idempotency check** | Returns cached result if key was already processed — safe client retries |
| 2 | **User eligibility** | Active status + KYC verified — hard gate before any funds move |
| 3 | **Bet limits** | Stake vs user-configured daily limit — regulatory requirement |
| 4 | **Session validation** | Active session owned by this user — anti-replay |
| 5 | **Risk evaluation** | Score via `RiskService` (80ms timeout, circuit-breaker protected) |
| 6 | **Fund reservation** | Debit from available → reserved balance (atomic, idempotent) |
| 7 | **Bet record creation** | Persisted with risk score, decision, wallet tx reference |
| 8 | **Instant settlement** | Crash/slots games settle immediately via deterministic HMAC-SHA256 |

The entire flow is wrapped in a `tracer.startActiveSpan('bet.place')` span with attributes for `bet.id`, `bet.risk_score`, `bet.risk_decision`, `bet.duration_ms`, and `bet.idempotency_hit`.

### `WalletService` — Reserve/release model

Funds move through three states:

```
available  →  reserved  →  released (win: back to available + payout credit)
                        →  forfeited (loss: reserve cleared, no credit)
                        →  voided (reserve returned to available)
```

Every operation carries an idempotency key derived from the bet ID. Concurrent retries are safe; concurrent double-executions are impossible.

### `RiskService` — Inline rule engine

Four signals evaluated synchronously on every bet:

| Signal | Threshold | Score |
|---|---|---|
| High-value single bet | ≥ $1,000 | +20 |
| Rapid velocity | > 30 bets in 60s | +30 |
| Approaching daily loss limit | > 80% of limit | +10 |
| Account tier blocked | `riskTier === 'blocked'` | → 100 |

| Score range | Tier | Decision |
|---|---|---|
| < 20 | `low` | allow |
| 20–39 | `standard` | allow |
| 40–59 | `elevated` | allow |
| 60–79 | `high` | review |
| ≥ 80 | `blocked` | reject |

Circuit breaker (opossum): 30% error rate over 5 samples → open. Reset after 15s. **Fail-closed** — an open circuit rejects with `riskScore: 100, decision: reject`. A risk service outage never silently passes unscored bets through.

### `AuthService` — Token rotation

- Access tokens: HS256, 15-minute expiry, carries `sub`, `sessionId`, `roles`, `riskTier`
- Refresh tokens: hashed (`bcrypt`, rounds=10) and stored in `sessions` table
- Single-use refresh rotation: consuming a refresh token marks it `used_at` — reuse returns 401
- Session revocation: `revoked_at` timestamp checked on every token refresh

---

## Telemetry Contracts

### Metrics — `telemetry/metrics.ts`

All instruments follow the `y_eet_{domain}_{operation}_{unit}_total` naming convention.

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

> **Note:** `y_eet_http_*` are app-layer metrics for route/synthetic context. Do not use these for RED metrics in SLO calculations — use `istio_requests_total` and `istio_request_duration_milliseconds` from Istio sidecar telemetry instead.

### Traces — `telemetry/tracer.ts`

OTEL SDK initialized before all other imports. Auto-instruments HTTP, pg, and Node core. Key spans:

- `bet.place` — full placement pipeline, attributes: `bet.game_id`, `bet.amount_usd`, `bet.risk_score`, `bet.risk_decision`, `bet.id`, `bet.duration_ms`
- HTTP spans suppressed for `/health/*` and `/metrics` paths
- `db.*` spans from pg auto-instrumentation include `db.statement` (redacted in prod by collector processor)

All spans carry resource attributes: `service.name`, `service.version`, `deployment.environment`, `k8s.cluster.name`, `k8s.namespace.name`, `k8s.pod.name`, `k8s.node.name`.

### Logs — `telemetry/logger.ts`

Pino JSON logger. Every log line emitted via this logger includes `trace_id` and `span_id` from the active OTEL context — automatically correlatable with Tempo traces in Grafana.

Fastify's built-in logger also injects trace context via the `mixin` option in `app.ts`. All request lifecycle logs (errors, responses) include `trace_id`.

Error responses always include `trace_id` — clients can hand this to support for exact trace lookup.

### Synthetic traffic tagging

Requests with `X-Synthetic: true` header set `request.isSynthetic = true`. This flows into:
- HTTP metric labels (`synthetic: "true"`)
- Fastify request serializer log field
- Istio Telemetry CR custom tag (`synthetic.check`) — triggers 100% sampling for synthetic traces

---

## Middleware

### `idempotencyGuard(namespace, path)`

`preHandler` hook. On first request: stores key → executes handler → `onSend` hook persists response body + status. On replay: returns cached response immediately with `X-Idempotency-Replay: true`. The store failure is non-fatal — if the store is down, requests proceed without idempotency protection (logged as a warning).

### `registerRequestMiddleware(fastify)`

Registered once on the root instance. Propagates `X-Request-ID` (or generates UUID), sets `request.isSynthetic`, records `y_eet_http_requests_total` and `y_eet_http_request_duration_ms` on every response, echoes `X-Service-Version` and `X-Request-ID` headers back.

---

## Health Endpoints

| Endpoint | Condition | Kubernetes probe |
|---|---|---|
| `GET /health/live` | Process running | Liveness |
| `GET /health/ready` | DB reachable | Readiness |
| `GET /health/startup` | DB reachable (one-time) | Startup |
| `GET /health/dependencies` | DB latency breakdown | Dashboards / runbooks |

---

## Environment Variables

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | `postgres://y_eet:y_eet@localhost:5432/y_eet` | |
| `JWT_SECRET` | *(dev placeholder)* | Must be ≥32 chars in production |
| `JWT_EXPIRY` | `15m` | Pair with refresh tokens |
| `REFRESH_TOKEN_EXPIRY_DAYS` | `7` | |
| `BCRYPT_ROUNDS` | `12` | Lower in test (`8`) for speed |
| `RATE_LIMIT_MAX` | `100` | Requests per window |
| `RATE_LIMIT_WINDOW_MS` | `60000` | 1 minute |
| `RISK_EVAL_TIMEOUT_MS` | `80` | Circuit breaker opens at this latency |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://localhost:4317` | OTEL Collector gRPC endpoint |
| `PROMETHEUS_PORT` | `9464` | Metrics scrape port (separate from app) |
| `LOG_LEVEL` | `info` | `trace\|debug\|info\|warn\|error\|silent` |
| `K8S_CLUSTER_NAME` | `local` | Injected via Downward API in K8s |
| `K8S_NAMESPACE` | `local` | Injected via Downward API |
| `K8S_POD_NAME` | `local` | Injected via Downward API |
| `K8S_NODE_NAME` | `local` | Injected via Downward API |
