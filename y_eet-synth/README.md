# y_eet-synth

> Production-grade synthetic traffic generator and service mesh validator for the Yeet Crypto-Casino Platform — written in Go.

An internal reliability and platform engineering tool. Generates realistic mixed synthetic traffic against the Yeet API, validates Istio mesh policies, injects chaos faults, and emits a structured pass/fail verdict for CI/CD gates.

---

## Capabilities

| Capability | Detail |
|---|---|
| **Realistic traffic** | 8 user archetypes with weighted scenario selection and configurable think-time |
| **Full API coverage** | Auth, users, wallet, bets, game sessions, risk, config flags, health, admin (internal) |
| **Idempotency support** | `Idempotency-Key` on all mutating requests; replay detection via `X-Idempotency-Replay` header |
| **Istio mesh validation** | Retry, timeout, circuit breaker, canary split, mTLS, trace propagation, ingress |
| **Chaos / fault injection** | Stale tokens, malformed payloads, duplicate replay, missing idempotency key, oversized payloads |
| **W3C trace propagation** | Every request carries `traceparent`; checks that the service echoes it through |
| **Pass/fail evaluation** | Threshold-based verdict with per-check breakdown; standard non-zero exit codes |
| **CI/CD ready** | Single binary, JSON report, Makefile CI targets, exits 0/1/2/3 |
| **No runtime dependencies** | Compiled Go binary — no pip, no virtualenv, no interpreter required |

---

## Quick Start

```bash
# 1. Build (requires Go 1.21+)
cd y_eet-synth
make build

# Or just use make targets — they build first automatically:
make smoke                              # 30s sanity check
make run-normal BASE_URL=http://localhost:8080
make run-mesh
make run-canary CANARY_VER=v2.1.0 CANARY_W=0.15
```

**No setup step required.** Go compiles a self-contained binary — no virtual environment to create, no packages to install at runtime.

---

## Setup Requirements

| Requirement | Version |
|---|---|
| Go | 1.21+ |
| Target platform running | Any (see `BASE_URL`) |

```bash
# Fetch dependencies (only needed once after checkout)
go mod download

# Build the binary
go build -o y_eet-synth .

# Or use make
make build
```

---

## Build Instructions

```bash
# Standard build
make build                     # produces ./y_eet-synth

# Clean build artifacts
make clean

# Cross-compile for Linux CI runners
GOOS=linux GOARCH=amd64 go build -o y_eet-synth-linux .
```

---

## CLI Usage

All commands share a common set of flags:

```
--base-url        API base URL (env: SYNTH_BASE_URL)  [default: http://localhost:8080]
--config          Path to a YAML profile config file   (env: SYNTH_CONFIG)
--log-level       DEBUG | INFO | WARNING | ERROR       [default: INFO]
--no-tls-verify   Disable TLS certificate verification
--json-report     Write JSON report to this path       (env: SYNTH_JSON_REPORT)
```

### Commands

```bash
# Quick smoke test — 30s, 5 rps, all endpoint categories
y_eet-synth smoke --base-url https://api.y_eet.com

# Run with a named profile
y_eet-synth run --profile normal --duration 300
y_eet-synth run --profile burst  --duration 180
y_eet-synth run --profile low    --rps 5

# Istio / service mesh validation
y_eet-synth mesh --validate-all --duration 120

# Canary split verification
y_eet-synth canary --expected-version v2.1.0 --expected-weight 0.20

# Chaos / fault-path validation (staging only)
y_eet-synth chaos --duration 180

# W3C traceparent continuity check
y_eet-synth trace --sample-size 200

# Retry and timeout verification
y_eet-synth retry --duration 60

# List all traffic profiles
y_eet-synth list-profiles
```

### Makefile shortcuts

```bash
make smoke                                # CI smoke gate
make run-normal                           # Standard production run
make run-mesh                             # Mesh validation
make run-canary CANARY_VER=v2.1 CANARY_W=0.10
make run-chaos                            # Staging only
make ci-smoke  BASE_URL=https://api-staging.y_eet.com
make ci-mesh   BASE_URL=https://api-staging.y_eet.com
make ci-canary BASE_URL=https://api-staging.y_eet.com CANARY_VER=v2.1 CANARY_W=0.15
```

---

## Traffic Profiles

| Profile | Concurrency | RPS | Duration | Notes |
|---|---|---|---|---|
| `smoke` | 5 | 5 | 30s | CI smoke gate — fast pass/fail |
| `low` | 5 | 10 | 120s | Off-peak / regression checks |
| `normal` | 20 | 50 | 300s | Representative production traffic |
| `burst` | 80 | 200 | 180s | Match/promo spike — 4× burst windows every 30s |
| `chaos` | 15 | 30 | 180s | Fault injection enabled |
| `mesh` | 10 | 20 | 120s | Istio mesh validation focused |
| `canary` | 10 | 25 | 120s | Canary split verification |
| `flood` | 300 | 500 | 600s | Peak stress — 5× burst every 90s |
| `onboarding` | 150 | 200 | 300s | Marketing surge — 55% registration funnel |

Profile parameters (concurrency, RPS, duration) are overridable via CLI flags or a YAML config file.

---

## User Behaviour Archetypes

Each goroutine picks a scenario by weighted random selection on every iteration:

| Archetype | Default weight | Flow |
|---|---|---|
| `anonymous` | 10% | Health probes — `/health/live`, `/health/ready`, `/health/dependencies` |
| `authenticated` | 25% | Session validate → profile → limits → config flags → feature flag |
| `active_bettor` | 45% | Balance → create session → N bets → bet history |
| `wallet_heavy` | 15% | Deposit → balance → transaction pages → optional withdraw → risk signal |
| `admin` | 5% | `/_internal/status`, config, db stats (requires admin token) |
| `registration_funnel` | opt-in | Register-like flow → profile → deposit → first bets |
| `high_roller` | opt-in | Large deposits → rapid high-value bets → risk score → partial withdraw |
| `live_event_bettor` | opt-in | Rapid burst bets on a single live-game session |

Weights are defined per-profile and fully configurable in YAML.

---

## Istio Validation Checks

Run with `y_eet-synth mesh --validate-all`.

| Check | What it validates | Pass condition |
|---|---|---|
| **retry_validation** | `x-envoy-attempt-count` header presence | Header parsed correctly; retries detectable |
| **timeout_validation** | Health endpoint reachability under timeout policy | 200 response; latency within bounds |
| **circuit_breaker_validation** | 503s under short flood burst | 503 observed OR clean handling under load |
| **trace_propagation** | `traceparent` echo rate | ≥ 95% of responses echo a trace context header |
| **mtls_validation** | `Server: istio-envoy` header presence | Traffic confirmed through Istio sidecar |
| **canary_split_validation** | Version header distribution | Observed split within ±5% of declared weight |
| **fault_injection_validation** | Abort rate under VirtualService fault rule | Observed fault rate within ±10% of configured % |
| **ingress_routing** | Base URL reachable via Gateway | HTTP 200 from `/health/live` |

**Canary validation** requires an Istio `VirtualService` routing a percentage to a subset and setting `x-canary-version` (or `x-version` / `x-app-version`) in responses.

**Fault injection validation** requires an active VirtualService fault rule, e.g.:

```yaml
fault:
  abort:
    percentage:
      value: 30.0
    httpStatus: 503
```

---

## Chaos Scenarios

Run with `y_eet-synth chaos`. Each scenario validates server-side error handling:

| Scenario | What it tests | Expected response |
|---|---|---|
| `stale_token` | Deliberately invalid JWT | 401 or 403 |
| `malformed_payload` | Non-JSON body on a JSON endpoint | 400 or 422 |
| `duplicate_replay` | Same idempotency key sent twice | 2xx (idempotent) or 409 |
| `missing_idempotency_key` | Omits key on a write endpoint | 400 or 2xx (if optional) |
| `oversized_payload` | 1 MB body | 413 or 400 |

> **WARNING:** Run chaos mode only in staging or controlled environments.

---

## Report Output

Every run writes a JSON report (default: `report.json`):

```json
{
  "generated_at": "2026-04-07T12:00:00Z",
  "duration_seconds": 300.4,
  "total_requests": 15200,
  "rps_average": 50.6,
  "global_error_rate_pct": 0.8,
  "global_p99_ms": 412.0,
  "endpoints": {
    "POST /api/v1/bets/place": {
      "total": 3200,
      "success_rate_pct": 99.2,
      "error_rate_pct": 0.8,
      "p50_ms": 95.0,
      "p95_ms": 280.0,
      "p99_ms": 410.0,
      "timeouts": 0,
      "retried": 8,
      "avg_attempt_count": 1.003,
      "idempotency_hits": 0,
      "auth_failures": 0,
      "via_istio_pct": 100.0,
      "status_codes": {"201": 3174, "402": 26},
      "canary_distribution": {},
      "trace_propagation_rate_pct": 0.0
    }
  },
  "mesh": [
    {"check": "retry_validation", "status": "PASS", "message": "...", "details": {...}},
    {"check": "trace_propagation", "status": "PASS", "message": "...", "details": {...}}
  ],
  "chaos": [
    {"scenario": "stale_token", "passed": true, "expected_status": 401, "status_code": 401}
  ],
  "evaluation": {
    "verdict": "PASS",
    "exit_code": 0,
    "confidence": 100.0,
    "checks": [
      {"name": "global_error_rate", "verdict": "PASS", "observed": 0.8, "threshold": 2.0, "unit": "%"}
    ]
  }
}
```

Terminal output shows a formatted table per endpoint, mesh check results, and a coloured evaluation summary.

---

## Exit Codes

| Code | Meaning | CI action |
|---|---|---|
| `0` | All checks passed | Proceed |
| `1` | One or more FAIL checks | Block pipeline |
| `2` | All passed but WARNs present | Review before merge |
| `3` | Insufficient data to evaluate | Re-run with longer duration |

---

## Observability Integration

Every synthetic request carries standard identification headers:

| Header | Value | Purpose |
|---|---|---|
| `X-Synthetic` | `true` | Filter synthetic traffic in Grafana / Loki (`{synthetic="true"}`) |
| `X-Request-ID` | UUID per request | Correlates with server `request_id` field in logs |
| `traceparent` | W3C TraceContext | Enables trace stitching in Tempo / Jaeger |

Envoy / Istio response headers captured per request:

| Header | What it tells you |
|---|---|
| `x-envoy-attempt-count` | How many retry attempts Istio made |
| `x-envoy-upstream-service-time` | Upstream latency without network overhead |
| `x-canary-version` / `x-version` | Which deployment served this request |
| `x-idempotency-replay` | Server confirmed idempotent cache hit |
| `Server: istio-envoy` | Traffic is flowing through the mesh sidecar |

---

## CI/CD Integration

### GitHub Actions example

```yaml
jobs:
  synth-smoke:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with:
          go-version: '1.21'
      - name: Build synth
        run: cd y_eet-synth && go build -o y_eet-synth .
      - name: Smoke test
        run: ./y_eet-synth/y_eet-synth smoke
               --base-url ${{ vars.STAGING_API_URL }}
               --json-report report.json
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: synth-report
          path: y_eet-synth/report.json

  synth-mesh:
    needs: synth-smoke
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: {go-version: '1.21'}
      - run: cd y_eet-synth && make ci-mesh BASE_URL=${{ vars.STAGING_API_URL }}

  canary-gate:
    if: github.event_name == 'deployment'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: {go-version: '1.21'}
      - run: |
          cd y_eet-synth && make ci-canary \
            BASE_URL=${{ vars.STAGING_API_URL }} \
            CANARY_VER=${{ vars.CANARY_VERSION }} \
            CANARY_W=${{ vars.CANARY_WEIGHT }}
```

### Environment variables

| Variable | Description | Default |
|---|---|---|
| `SYNTH_BASE_URL` | API base URL | `http://localhost:8080` |
| `SYNTH_INTERNAL_URL` | Internal API base URL | same as base |
| `SYNTH_CONFIG` | Path to YAML config file | — |
| `SYNTH_LOG_LEVEL` | Log verbosity | `INFO` |
| `SYNTH_TLS_VERIFY` | TLS verification | `true` |
| `SYNTH_TOKEN_POOL_SIZE` | Synthetic user pool size | `20` |
| `SYNTH_JSON_REPORT` | JSON report output path | `report.json` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint | `http://localhost:4317` |

---

## Configuration File

Override any profile or threshold setting with a YAML file:

```yaml
# config/my-profile.yaml
base_url: https://api-staging.y_eet.com
token_pool_size: 50
json_report_path: /tmp/synth-report.json

profile:
  name: custom
  concurrency: 30
  duration_seconds: 600
  rps_target: 80.0
  scenario_weights:
    anonymous: 0.05
    authenticated: 0.20
    active_bettor: 0.55
    wallet_heavy: 0.15
    admin: 0.05

thresholds:
  max_error_rate: 0.01          # 1% error ceiling
  p99_latency_ms: 1000.0        # 1s P99 ceiling
  max_timeout_rate: 0.002

mesh:
  validate_retries: true
  validate_trace_propagation: true
  validate_mtls: true
```

```bash
y_eet-synth run --config config/my-profile.yaml
```

---

## Project Structure

```
y_eet-synth/
├── main.go                  CLI entrypoint (cobra commands)
├── go.mod / go.sum          Go module dependencies
├── Makefile                 Build and run shortcuts
├── config/
│   ├── default.yaml         Default profile overrides
│   ├── canary.yaml          Canary validation profile
│   ├── mesh.yaml            Mesh validation profile
│   └── chaos.yaml           Chaos profile
└── internal/
    ├── config/              Config structs + YAML/env loader
    ├── profiles/            All traffic profile definitions
    ├── client/              HTTP client: headers, timing, Istio header capture
    ├── metrics/             In-process latency histograms + counters
    ├── token/               JWT token pool: seed, refresh, rotate
    ├── scenarios/           User behaviour archetypes (8 types)
    ├── runner/              Concurrent traffic engine + token-bucket rate limiter
    ├── mesh/                Istio validation checks (8 check categories)
    ├── chaos/               Fault injection scenarios
    ├── evaluator/           Pass/fail verdict + exit codes
    └── reporter/            Terminal table output + JSON report writer
```

---

## Troubleshooting

**`connection refused` on startup** — the API must be running and accepting connections. Check `BASE_URL` and that the Docker stack is up.

**All scenarios skipped (empty token pool)** — the `/api/v1/auth/register` endpoint is not returning 201. Verify migrations have run and the API is healthy.

**`INSUFFICIENT_DATA` verdict** — run duration is too short or RPS too low. Use a longer `--duration` or a higher-concurrency profile.

**Mesh checks return SKIP** — validate that the token pool seeded at least one user (check `INFO` log lines for `Token pool: ready`).

**TLS errors against staging** — pass `--no-tls-verify` if the staging cert is self-signed, or set `SYNTH_TLS_VERIFY=false`.
