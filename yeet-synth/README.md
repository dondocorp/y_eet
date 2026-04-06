# yeet-synth

**Production-grade synthetic traffic generator and service mesh validator for the Yeet iGaming Platform.**

This is an internal reliability and platform engineering tool. It is not a demo load script.
It generates realistic mixed synthetic traffic, validates Istio service mesh behaviour, produces
OTel telemetry, and emits a machine-readable pass/fail verdict for CI/CD gates.

---

## What it does

| Capability | Detail |
|---|---|
| Realistic traffic generation | 5 user archetypes, weighted scenario selection, think-time simulation |
| Full API coverage | Auth, users, wallet, bets, game sessions, risk, config, health, admin |
| Idempotency support | Correct Idempotency-Key usage + replay detection |
| Istio mesh validation | Retry, timeout, circuit breaker, canary split, mTLS, trace propagation, ingress |
| Chaos / fault injection | Stale tokens, malformed payloads, duplicate replay, rate-limit trigger, missing headers |
| OTel instrumentation | W3C traceparent propagation on every request; OTLP export to your collector |
| Pass/fail evaluation | Threshold-based verdict with per-check breakdown; non-zero exit code on failures |
| CI/CD ready | Single exit code, JSON report, Makefile CI targets, GitLab CI examples |

---

## Quick start

```bash
# 1. Set up
cd yeet-synth
make install
cp .env.example .env
# Edit .env — at minimum set SYNTH_BASE_URL

# 2. Run a smoke test
make smoke

# 3. Run normal traffic
make run-normal

# 4. Validate service mesh
make run-mesh

# 5. Validate canary split (requires active canary deployment)
make run-canary CANARY_VERSION=v2.1.0 CANARY_WEIGHT=0.15
```

---

## Traffic profiles

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

## User behaviour archetypes

The runner picks a scenario for each worker iteration using weighted random selection:

| Archetype | Default weight | Flow |
|---|---|---|
| `anonymous` | 10% | health checks, warmup probes |
| `authenticated` | 25% | login → profile → limits → config flags → validate session |
| `active_bettor` | 45% | balance → create session → N bets + heartbeats → history → close |
| `wallet_heavy` | 15% | deposit → balance → transaction history → optional withdraw → risk signal |
| `admin` | 5% | `/_internal/status`, config, db stats (requires admin token) |

Weights are configurable per profile in YAML or by editing `synth/profiles.py`.

---

## Istio validation checks

Run `python main.py mesh --validate-all` to execute all checks.

| Check | What it measures | Pass condition |
|---|---|---|
| **Retry validation** | `x-envoy-attempt-count` distribution | avg attempts < 1.5; no unsafe retries on non-idempotent endpoints |
| **Timeout validation** | Mesh vs app timeout alignment | No 504s without corresponding mesh timeouts; p99 within SLO |
| **Circuit breaker** | Behaviour under high load flood | 503s observed at expected threshold OR service handles load cleanly |
| **Canary split** | Version header distribution across N requests | Observed split within ±5% of declared weight |
| **Fault injection** | Abort/delay fault rate match VirtualService policy | Observed fault rate within ±15% of expected |
| **mTLS / policy** | Istio sidecar presence; unexpected 403s | `server: istio-envoy` in ≥1 response; policy_failures < 5% |
| **Ingress routing** | Base paths return expected status codes | No 404s on valid routes |
| **Trace propagation** | `traceparent` continuity | ≥95% of traced requests have trace context visible in response |

### Enabling specific mesh features

**Canary validation** requires an Istio `VirtualService` that routes a percentage of traffic to a
subset and sets a version identifier header (e.g. `x-canary-version`).

**Fault injection validation** requires an active `VirtualService` fault rule:
```yaml
fault:
  abort:
    percentage:
      value: 30.0
    httpStatus: 503
```
Then run: `python main.py run --config config/mesh.yaml` after setting `validate_fault_injection: true`.

---

## CLI reference

```
python main.py smoke                       # Quick 30s sanity check
python main.py run --profile normal        # Normal production traffic
python main.py run --profile burst         # Burst/spike simulation
python main.py mesh --validate-all         # Full Istio validation
python main.py canary \
  --expected-version v2.1 \
  --expected-weight 0.10                  # Canary split verification
python main.py chaos                       # Fault-path validation (staging only)
python main.py trace --sample-size 200    # Trace propagation check
python main.py retry --duration 60        # Retry/timeout verification
python main.py list-profiles              # Show all profiles
```

All commands support `--base-url`, `--config`, `--log-level`, `--no-tls-verify`, `--json-report`.

---

## Metrics produced

Every run emits a structured JSON report (`report.json` by default) containing:

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

The terminal output additionally shows Rich-formatted tables for all of the above.

---

## Observability integration

Every synthetic request carries:
- `X-Synthetic: true` — allows filtering synthetic traffic in Grafana / Kibana dashboards
- `X-Request-ID` — unique per request, correlates with server logs (`request_id` field)
- `traceparent` — W3C TraceContext, enabling trace stitching in Tempo / Jaeger / Zipkin

**Grafana**: Add `{synthetic="true"}` filter to dashboards to isolate synthetic traffic,
or use it as a separate signal source for SLO burn-rate calculations.

**Istio dashboards (Kiali/Grafana)**: The `X-Synthetic` header is transparent to the mesh.
Traffic appears in Kiali topology and Istio service dashboards exactly as real traffic would,
but can be separated via log filtering.

**Alerting**: Because synthetic traffic uses the same OTel pipeline, any firing alert on a
synthetic-originated trace indicates a real reliability problem. Synthetic traffic should be
part of your SLO error budget tracking — not excluded from it.

---

## CI/CD integration

### GitLab CI example

```yaml
# .gitlab-ci.yml

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
      when: on_success

post-deploy-mesh-validation:
  stage: verify
  image: python:3.11-slim
  script:
    - cd yeet-synth && pip install -r requirements.txt -q
    - python main.py mesh --validate-all --duration 120 \
        --base-url $SYNTH_BASE_URL --json-report report-mesh.json
  allow_failure: false   # mesh failures block the pipeline
  artifacts:
    paths:
      - yeet-synth/report-mesh.json
    when: always
  rules:
    - if: '$CI_COMMIT_BRANCH == "master"'
      when: on_success

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
  artifacts:
    paths:
      - yeet-synth/report-canary.json
    when: always
  rules:
    - if: '$CI_PIPELINE_SOURCE == "schedule" && $CANARY_ACTIVE == "true"'
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | All checks passed |
| 1 | One or more FAIL checks — block pipeline |
| 2 | All passed but WARNs present — review before merging |
| 3 | Insufficient data to evaluate |

---

## Chaos mode — safe use guidelines

`python main.py chaos` is designed to be safe in staging:

- It does not delete or corrupt data
- It uses synthetic user accounts (registered on-the-fly)
- Malformed requests are constructed to test validation, not bypass it
- Rate limit bursts are bounded (120 requests) and short-lived
- Stale token tests use a pre-expired JWT that cannot authenticate

**Do not run chaos mode in production** without:
1. An incident response channel open
2. An on-call engineer monitoring dashboards
3. A tested rollback procedure

---

## Project structure

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
