# yeet-synth

> Production-grade synthetic traffic generator and service mesh validator for the Yeet Crypto-Casino Platform.

An internal reliability and platform engineering tool. Generates realistic mixed synthetic traffic, validates Istio service mesh behaviour, produces OTel telemetry, and emits a machine-readable pass/fail verdict for CI/CD gates.

---

## Capabilities

| Capability | Detail |
|---|---|
| **Realistic traffic** | 5 user archetypes, weighted scenario selection, think-time simulation |
| **Full API coverage** | Auth, users, wallet, bets, game sessions, risk, config, health, admin |
| **Idempotency support** | Correct `Idempotency-Key` usage + replay detection |
| **Istio mesh validation** | Retry, timeout, circuit breaker, canary split, mTLS, trace propagation, ingress |
| **Chaos / fault injection** | Stale tokens, malformed payloads, duplicate replay, rate-limit trigger, missing headers |
| **OTel instrumentation** | W3C `traceparent` propagation on every request; OTLP export to your collector |
| **Pass/fail evaluation** | Threshold-based verdict with per-check breakdown; non-zero exit code on failures |
| **CI/CD ready** | Single exit code, JSON report, Makefile CI targets |

---

## Quick Start

```bash
# 1. Set up
cd yeet-synth
make install
cp .env.example .env
# Edit .env — set SYNTH_BASE_URL at minimum

# 2. Smoke test (30s)
make smoke

# 3. Normal traffic (5 min)
make run-normal

# 4. Validate service mesh
make run-mesh

# 5. Canary split validation
make run-canary CANARY_VERSION=v2.1.0 CANARY_WEIGHT=0.15
```

---

## Traffic Profiles

| Profile | Concurrency | RPS | Duration | Notes |
|---|---|---|---|---|
| `smoke` | 5 | 5 | 30s | CI smoke gate |
| `low` | 5 | 10 | 120s | Off-peak / regression |
| `normal` | 20 | 50 | 300s | Representative production |
| `burst` | 80 | 200 | 180s | Match/promo spike (4× burst windows) |
| `chaos` | 15 | 30 | 180s | Fault injection enabled |
| `mesh` | 10 | 20 | 120s | Mesh validation focused |
| `canary` | 10 | 25 | 120s | Canary split verification |

---

## User Behaviour Archetypes

Each worker iteration picks a scenario via weighted random selection:

| Archetype | Default weight | Flow |
|---|---|---|
| `anonymous` | 10% | Health checks, warmup probes |
| `authenticated` | 25% | Login → profile → limits → config flags → validate session |
| `active_bettor` | 45% | Balance → create session → N bets + heartbeats → history → close |
| `wallet_heavy` | 15% | Deposit → balance → transaction history → optional withdraw → risk signal |
| `admin` | 5% | `/_internal/status`, config, db stats (requires admin token) |

Weights are configurable per profile in YAML or in `synth/profiles.py`.

---

## Istio Validation Checks

Run with `python main.py mesh --validate-all`.

| Check | What it measures | Pass condition |
|---|---|---|
| **Retry validation** | `x-envoy-attempt-count` distribution | avg attempts < 1.5; no unsafe retries on non-idempotent endpoints |
| **Timeout validation** | Mesh vs app timeout alignment | No 504s without corresponding mesh timeouts; p99 within SLO |
| **Circuit breaker** | Behaviour under high-load flood | 503s observed at expected threshold OR service handles load cleanly |
| **Canary split** | Version header distribution across N requests | Observed split within ±5% of declared weight |
| **Fault injection** | Abort/delay fault rate match VirtualService policy | Observed fault rate within ±15% of expected |
| **mTLS / policy** | Istio sidecar presence; unexpected 403s | `server: istio-envoy` in ≥1 response; policy_failures < 5% |
| **Ingress routing** | Base paths return expected status codes | No 404s on valid routes |
| **Trace propagation** | `traceparent` continuity | ≥95% of traced requests have trace context visible in response |

### Enabling mesh features

**Canary validation** requires an Istio `VirtualService` that routes a percentage to a subset and sets a version identifier header (`x-canary-version`).

**Fault injection validation** requires an active `VirtualService` fault rule:

```yaml
fault:
  abort:
    percentage:
      value: 30.0
    httpStatus: 503
```

Then run: `python main.py run --config config/mesh.yaml` with `validate_fault_injection: true`.

---

## CLI Reference

```bash
python main.py smoke                       # Quick 30s sanity check
python main.py run --profile normal        # Normal production traffic
python main.py run --profile burst         # Burst/spike simulation
python main.py mesh --validate-all         # Full Istio validation
python main.py canary \
  --expected-version v2.1 \
  --expected-weight 0.10                   # Canary split verification
python main.py chaos                       # Fault-path validation (staging only)
python main.py trace --sample-size 200     # Trace propagation check
python main.py retry --duration 60         # Retry/timeout verification
python main.py list-profiles               # Show all profiles
```

All commands accept `--base-url`, `--config`, `--log-level`, `--no-tls-verify`, `--json-report`.

---

## Report Output

Every run emits a structured JSON report (`report.json` by default):

```
total_requests, rps_average, global_error_rate_pct, global_p99_ms
per endpoint:
  total, success_rate_pct, error_rate_pct
  p50_ms, p95_ms, p99_ms
  timeouts, retried, avg_attempt_count
  idempotency_hits, auth_failures
  via_istio_pct, status_codes{}
  canary_distribution{}, trace_propagation_rate_pct
mesh[]: check, status, message, details{}
chaos[]: scenario, passed, expected, got, note
evaluation: verdict, exit_code, confidence, checks[]
```

Terminal output additionally shows Rich-formatted tables for all sections above.

---

## Observability Integration

Every synthetic request carries:

| Header | Value | Purpose |
|---|---|---|
| `X-Synthetic` | `true` | Allows filtering synthetic traffic in Grafana / Loki dashboards |
| `X-Request-ID` | unique per request | Correlates with server logs (`request_id` field) |
| `traceparent` | W3C TraceContext | Enables trace stitching in Tempo / Jaeger / Zipkin |

**Grafana** — Use `{synthetic="true"}` to isolate synthetic traffic, or as a separate signal source for SLO burn-rate calculations.

**Alerting** — Synthetic traffic uses the same OTel pipeline. An alert firing on a synthetic-originated trace indicates a real reliability problem. Synthetic traffic should be part of your SLO error budget — not excluded from it.

---

## CI/CD Integration

### Exit codes

| Code | Meaning |
|---|---|
| `0` | All checks passed |
| `1` | One or more FAIL checks — block pipeline |
| `2` | All passed but WARNs present — review before merging |
| `3` | Insufficient data to evaluate |

### GitLab CI example

```yaml
stages:
  - deploy
  - verify

variables:
  SYNTH_BASE_URL: "https://api-staging.yeet.com"

smoke-test:
  stage: verify
  image: python:3.11-slim
  script:
    - cd yeet-synth && pip install -r requirements.txt -q
    - python main.py smoke --base-url $SYNTH_BASE_URL --json-report report.json
  artifacts:
    reports:
      junit: report.json
    paths:
      - yeet-synth/report.json
    when: always
  rules:
    - if: '$CI_COMMIT_BRANCH == "master"'

post-deploy-mesh-validation:
  stage: verify
  image: python:3.11-slim
  script:
    - cd yeet-synth && pip install -r requirements.txt -q
    - python main.py mesh --validate-all --duration 120
        --base-url $SYNTH_BASE_URL --json-report report-mesh.json
  allow_failure: false
  artifacts:
    paths:
      - yeet-synth/report-mesh.json
    when: always
  rules:
    - if: '$CI_COMMIT_BRANCH == "master"'

canary-gate:
  stage: verify
  image: python:3.11-slim
  script:
    - cd yeet-synth && pip install -r requirements.txt -q
    - python main.py canary
        --base-url $SYNTH_BASE_URL
        --expected-version $CANARY_VERSION
        --expected-weight $CANARY_WEIGHT
        --json-report report-canary.json
  allow_failure: false
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule" && $CANARY_ACTIVE == "true"'
```

---

## Chaos Mode — Safe Use Guidelines

`python main.py chaos` is designed to be safe in staging:

- Does not delete or corrupt data
- Uses synthetic user accounts (registered on-the-fly)
- Malformed requests test validation, not bypass it
- Rate limit bursts are bounded (120 requests) and short-lived
- Stale token tests use a pre-expired JWT that cannot authenticate

**Do not run chaos mode in production** without:
1. An incident response channel open
2. An on-call engineer monitoring dashboards
3. A tested rollback procedure

---

## Project Structure

```
yeet-synth/
├── main.py              CLI entrypoint (click)
├── synth/
│   ├── config.py        Config dataclasses + YAML/env loader
│   ├── client.py        Async HTTP client: OTel, retries, Istio header capture
│   ├── endpoints.py     All API endpoint call functions
│   ├── payloads.py      Faker-based realistic payload factory
│   ├── token_manager.py JWT token pool: seed, refresh, rotate
│   ├── scenarios.py     User behaviour archetypes (coroutines)
│   ├── profiles.py      Traffic profile definitions
│   ├── runner.py        Async concurrency engine + token-bucket rate limiter
│   ├── mesh.py          Istio validation scenarios (8 check categories)
│   ├── metrics.py       In-process metrics: histograms, counters, records
│   ├── otel.py          OpenTelemetry SDK setup + W3C propagation
│   ├── chaos.py         Fault injection helpers
│   ├── evaluator.py     Pass/fail evaluation model + exit codes
│   └── reporter.py      Rich terminal reporter + JSON output
├── config/
│   ├── default.yaml     Default profile
│   ├── canary.yaml      Canary validation profile
│   ├── mesh.yaml        Mesh validation profile
│   └── chaos.yaml       Chaos profile
├── .env.example
├── requirements.txt
└── Makefile
```
