# Challenge Status

> Requirement-by-requirement comparison of the Yeet SRE/DevOps role JD against what was delivered in this repository.

---

## Scorecard

| Category | Coverage |
|---|---|
| Tech stack requirements | 6 / 6 |
| Key responsibilities | 6 / 6 |
| Required skills | 9 / 10 |
| **Overall** | **21 / 22 — 95%** |

**The one gap:** CDK / CloudFormation — Terraform is used exclusively for all IaC.

**GitLab CI note:** The JD specifies GitLab CI. GitHub Actions is used instead on an identical pipeline model (lint → test → build → deploy → synthetic gate → SLO check). A drop-in GitLab equivalent is documented in [`y_eet-synth/README.md`](y_eet-synth/README.md).

---

## Beyond the Spec

7 production-grade features delivered that were not asked for:

| Feature | Description |
|---|---|
| **Brand Intelligence pipeline** | Full Python NLP subsystem — Reddit/Twitter scraping, RoBERTa sentiment classification, 13 Prometheus metrics, 3 Grafana dashboards, 7 Telegram alert rules, Streamlit analyst UI |
| **`y_eet-synth` Go CLI** | Purpose-built synthetic traffic generator and Istio mesh validator — 9 load profiles, 8 CLI commands, chaos fault injection, canary split validation, structured JSON report output |
| **Thanos long-term storage** | 13-month metric retention with 5m/1h downsampling on S3 + Glacier IR |
| **Istio service mesh** | mTLS STRICT mode, L7 traffic policy, circuit breaker, canary weight validation, fault injection |
| **Multi-window SLO burn-rate alerting** | Fast burn (1h / 14.4×) + slow burn (6h / 6×) across all 5 SLOs |
| **Provably fair gaming** | HMAC-SHA256 server-seed commitment scheme for crash and slots |
| **Reserve/release wallet model** | Atomic bet staking with no hot-path row locks and a zero double-spend guarantee |

---

## Tech Stack

| JD Requirement | Status | Delivered |
|---|---|---|
| **AWS** | Delivered | EKS + Karpenter, S3 + Glacier IR lifecycle, SQS + DLQ, RDS, ElastiCache, Secrets Manager, IRSA |
| **Docker** | Delivered | Every service containerised; `docker compose up` launches the full stack |
| **GitLab CI** | Delivered (GitHub Actions equivalent) | 5 workflows — same stages, gates, and artefacts; GitLab drop-in documented |
| **Terraform** | Delivered | Modular IaC — S3 remote state, OIDC auth, Terraform-managed observability components |
| **OpenTelemetry** | Delivered | Full OTEL SDK in API + social-sentiment; DaemonSet + Gateway collector with tail sampling |
| **CloudWatch** | Delivered | CloudWatch Exporter bridges RDS, SQS, and ElastiCache metrics into Prometheus |

**Where to look:** `terraform/modules/`, `terraform/environments/`, `.github/workflows/`, `src/telemetry/`, `observability/collector/`, `social-sentiment/observability/`

---

## Key Responsibilities

### 1 — Observability Best Practices

Full production-grade stack covering all four signals (traces, metrics, logs, dashboards):

| Signal | Implementation | Location |
|---|---|---|
| **Distributed traces** | OTEL SDK → Collector (tail sampling) → Tempo; W3C traceparent end-to-end | `observability/collector/otelcol-gateway.yaml`, `src/telemetry/tracer.ts` |
| **Metrics** | Prometheus + Thanos (13-month retention, S3 blocks, 5m/1h downsampling) | `observability/prometheus/`, `terraform/modules/prometheus/` |
| **Logs** | Fluent Bit DaemonSet → Loki (S3, 31d hot / 12m cold); log↔trace correlation via `trace_id` derived field | `observability/loki/`, `observability/loki/fluent-bit-daemonset.yaml` |
| **Dashboards** | 15+ Grafana dashboards in 5 folders — Executive, Services, Infrastructure, Reliability, Brand Intelligence | `observability/grafana/dashboards/` |
| **SLOs** | 5 SLOs with multi-window burn-rate alerts (fast: 1h / 14.4×, slow: 6h / 6×) | `observability/prometheus/rules/slo-burn-rate.yaml` |
| **Service mesh telemetry** | Istio 1.21 — mTLS, Envoy access logs, L7 spans, mesh traffic dashboard | `observability/istio/`, `observability/grafana/dashboards/infrastructure/istio-traffic.json` |
| **Brand intelligence** | Social sentiment pipeline — 13 `social_*` Prometheus metrics; 3 Grafana Brand Intelligence dashboards | `social-sentiment/metrics/exporter.py`, `observability/grafana/dashboards/brand-intelligence/` |

Leadership-facing view: the **Executive Health** dashboard (`observability/grafana/dashboards/platform-health/executive-health.json`) surfaces SLO burn rates, RPS, P99, and volume.

---

### 2 — Incident Response and Runbook Processes

Five runbooks covering the most common production failure modes:

| Runbook | Trigger alert | First action |
|---|---|---|
| [`api-outage.md`](observability/runbooks/api-outage.md) | `APIHigh5xxRateCritical` | Open Incident Triage dashboard |
| [`queue-lag.md`](observability/runbooks/queue-lag.md) | `SQSQueueDepthCritical` | Check consumer pod status |
| [`wallet-anomaly.md`](observability/runbooks/wallet-anomaly.md) | `WalletTransferFailureSpike` | Financial protocol — notify payments lead |
| [`collector-failure.md`](observability/runbooks/collector-failure.md) | `OTELCollectorDown` | Check collector pod logs |
| [`canary-regression.md`](observability/runbooks/canary-regression.md) | Post-deploy k6 failure | Run rollback decision tree |

All alert `annotations.runbook` fields in `observability/prometheus/rules/` link directly to the corresponding runbook URL.

---

### 3 — Code Reviews with Production Observability Focus

The CI pipeline enforces observability contracts automatically on every PR:

| Gate | What it checks | Location |
|---|---|---|
| `instrumentation-check` job | Every `src/services/*.ts` file must import from `telemetry/metrics` or `telemetry/tracer` — CI fails if missing | `.github/workflows/ci.yml` lines 42–73 |
| OTEL resource attribute check | `SEMRESATTRS_SERVICE_NAME` and `SEMRESATTRS_DEPLOYMENT_ENVIRONMENT` must be set in `tracer.ts` | `.github/workflows/ci.yml` lines 60–66 |
| `trace_id` in error responses | `src/app.ts` must include `trace_id` in the error response shape | `.github/workflows/ci.yml` lines 68–72 |
| Prometheus rule validation | `promtool check rules` runs on all alert rule YAML files | `.github/workflows/ci.yml` lines 91–101 |
| Dashboard JSON validation | All Grafana dashboard JSON must be valid and contain `uid`, `title`, `tags` | `.github/workflows/ci.yml` lines 111–139 |

---

### 4 — CI/CD Pipeline Development

Five GitHub Actions workflows:

| Workflow | Trigger | Key gates |
|---|---|---|
| `ci.yml` | PR / push to `master` or `dev` | Lint → typecheck → instrumentation check → observability config validation → unit tests (≥ 65% coverage) |
| `deploy.yml` | Push to `master` | Build → staging → prod + k6 post-deploy gate (blocks on failure) + SLO burn-rate check + Grafana deploy annotation |
| `observability-deploy.yml` | Changes to `observability/` or `terraform/` | Terraform plan/apply → dashboard push via Grafana API → PrometheusRules + Istio CRD apply |
| `synthetic-monitoring.yml` | Scheduled every 5 minutes | `y_eet-synth smoke` → login flow + bet placement dry-run → Slack alert on failure |
| `social-sentiment.yml` | Changes to `social-sentiment/` | Ruff lint → 6 test suites (≥ 70% coverage) → metrics contract + schema + keyword config validation → Docker build → GHCR push |

---

### 5 — Synthetic Traffic Generator — `y_eet-synth` (Go)

A purpose-built Go CLI that drives synthetic traffic, validates Istio mesh policies, injects fault scenarios, and gates canary rollouts. Used directly in CI via `synthetic-monitoring.yml` and `deploy.yml`.

**CLI commands:**

| Command | Purpose |
|---|---|
| `smoke` | 30s / 5 rps quick health check — exit 0 or 1 |
| `run --profile <name>` | Sustained traffic at a named profile |
| `mesh --validate-all` | Retries, timeouts, circuit breaker, mTLS, trace propagation, ingress |
| `canary --expected-version v2 --expected-weight 0.10` | Validates Istio traffic split is within tolerance |
| `chaos --duration 180` | Fault injection: stale token, malformed payload, duplicate replay, oversized body |
| `trace --sample-size 200` | W3C traceparent propagation check |
| `retry --duration 60` | Envoy retry + timeout header verification |
| `list-profiles` | Prints all profiles with concurrency / RPS / duration |

**Traffic profiles:**

| Profile | Concurrency | RPS | Duration | Notes |
|---|---|---|---|---|
| `smoke` | 5 | 5 | 30s | CI post-deploy gate |
| `low` | 5 | 10 | 120s | |
| `normal` | 20 | 50 | 300s | |
| `burst` | 80 | 200 | 180s | 4× burst every 30s for 15s |
| `chaos` | 15 | 30 | 180s | Fault injection enabled |
| `mesh` | 10 | 20 | 120s | Mesh validation enabled |
| `canary` | 10 | 25 | 120s | Canary + mesh validation |
| `onboarding` | 150 | 200 | 300s | 55% registration funnel |
| `flood` | 300 | 500 | 600s | 5× burst — load test only |

**Architecture** (`y_eet-synth/internal/`): `config` → `profiles` → `runner` (token-bucket rate limiter + goroutine pool) → `scenarios` (weighted picker) → `client` (HTTP with Envoy header capture) → `evaluator` → `reporter` (stdout + JSON).

**Exit codes:** 0 pass · 1 fail · 2 warn · 3 insufficient data — consumed directly by CI.

---

### 6 — Distributed Systems on AWS

| Component | AWS service | Notes |
|---|---|---|
| **Compute** | EKS 1.29 + Karpenter | Node autoscaling; pod scheduling in `betting` and `wallet` namespaces |
| **Object storage** | S3 Standard → Glacier IR lifecycle | Prometheus blocks, Loki chunks, Tempo traces |
| **Queue** | SQS + DLQ | Settlement async processing; `SQSDeadLetterQueueGrowing` alert fires on any DLQ message |
| **Database** | RDS (PostgreSQL) | Managed; metrics bridged via CloudWatch Exporter |
| **Cache** | ElastiCache | Metrics bridged via CloudWatch Exporter |
| **Secrets** | AWS Secrets Manager + IRSA | No static credentials in pod specs |
| **Container registry** | GHCR | Built and pushed by `social-sentiment.yml` and `deploy.yml` |

---

### 7 — Mentoring Junior Engineers

The `observability/README.md` contains a step-by-step **Adding a New Service** checklist — 7 steps covering instrumentation → resource attributes → RED metrics → dashboard → SLO → runbook → synthetic check. Each step references the exact file to copy or extend, making the process actionable without senior guidance.

---

## Required Skills

| Skill | Status | Evidence |
|---|---|---|
| **Linux scripting** | Delivered | `scripts/demo.sh` — 200-line Bash with preflight checks, wait loops, and process management; `social-sentiment/scripts/run_pipeline.sh` |
| **Python** | Delivered | Entire `social-sentiment/` subsystem — scraper, NLP, pipeline, alerts, metrics, dashboard, 6 test suites |
| **JavaScript / TypeScript** | Delivered | `src/` — Fastify 4 API, full business logic, typed repositories, OTEL SDK instrumentation |
| **Go** | Delivered | `y_eet-synth/` — cobra CLI, token-bucket rate limiter, concurrent runner, Istio mesh validator, chaos injector, canary split checker, JSON report output |
| **Terraform** | Delivered | `terraform/` — modular, S3 remote state, OIDC auth, separate prod/staging root modules |
| **CDK / CloudFormation** | Not delivered | Terraform used exclusively for IaC |
| **Microservice architecture** | Delivered | API (Node) + social-sentiment (Python) as separate containers with independent metrics endpoints, tracing namespaces, and Docker Compose services |
| **CI/CD pipeline development** | Delivered | 5 GitHub Actions workflows with lint, test, build, deploy, synthetic, and SLO gates |
| **Observability and monitoring** | Delivered | Full OTEL + Prometheus + Grafana + Loki + Tempo + Alertmanager + Thanos stack |
| **Incident response and troubleshooting** | Delivered | 5 runbooks in `observability/runbooks/`; Incident Triage dashboard; severity model with PagerDuty + Slack routing |

---

## One-Command Demo

```bash
./scripts/demo.sh
```

Starts the entire local stack, seeds Brand Intelligence demo data, runs synthetic traffic, and opens Grafana automatically. See the root [`README.md`](README.md) for flags and prerequisites.
