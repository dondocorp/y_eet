# Challenge Status

Comparison of the Yeet SRE/DevOps role requirements against what was delivered in this repository.

---

## Tech Stack

| JD Requirement | Delivered | Where |
|---|---|---|
| **AWS** | EKS, Karpenter, S3 + Glacier lifecycle, SQS, RDS, ElastiCache, Secrets Manager, IRSA | `terraform/modules/`, `observability/prometheus/rules/queue-infra.yaml`, root README Infrastructure table |
| **Docker** | Every service runs in Docker; `docker compose up` launches the full stack | `docker-compose.yml`, `scripts/demo.sh` |
| **GitLab CI** | GitHub Actions (functional equivalent — same stages, gates, and artefacts) | `.github/workflows/` — 5 workflows |
| **Terraform** | Modular IaC — S3 remote state, OIDC auth, Terraform-managed observability components | `terraform/environments/`, `terraform/modules/` |
| **OpenTelemetry** | Full OTEL SDK instrumentation in API + social-sentiment; DaemonSet + Gateway collector with tail sampling | `src/telemetry/`, `observability/collector/`, `social-sentiment/observability/tracer.py` |
| **CloudWatch** | CloudWatch Exporter bridges RDS, SQS, ElastiCache metrics into Prometheus | `observability/grafana/provisioning/datasources/` (CloudWatch datasource), `observability/README.md` Stack table |

> **CI/CD note:** The JD specifies GitLab CI. GitHub Actions is used instead; it supports the same pipeline model (lint → test → build → deploy → synthetic gate → SLO check). The `y_eet-synth/README.md` includes a full GitLab CI example showing how the synthetic tool integrates with GitLab pipelines.

---

## Key Responsibilities

### 1. Observability best practices

Full production-grade stack covering all four signals (traces, metrics, logs, dashboards):

| Signal | Implementation | Proof |
|---|---|---|
| **Distributed traces** | OTEL SDK → Collector (tail sampling) → Tempo; W3C traceparent end-to-end | `observability/collector/otelcol-gateway.yaml`, `src/telemetry/tracer.ts` |
| **Metrics** | Prometheus + Thanos (13-month retention, S3 blocks, 5m/1h downsampling) | `observability/prometheus/`, `terraform/modules/prometheus/` |
| **Logs** | Fluent Bit DaemonSet → Loki (S3, 31d hot / 12m cold); log↔trace correlation via `trace_id` derived field | `observability/loki/`, `observability/loki/fluent-bit-daemonset.yaml` |
| **Dashboards** | 15+ Grafana dashboards in 5 folders — Executive, Services, Infrastructure, Reliability, Brand Intelligence | `observability/grafana/dashboards/` |
| **SLOs** | 5 SLOs with multi-window burn-rate alerts (fast: 1h/14.4×, slow: 6h/6×) | `observability/prometheus/rules/slo-burn-rate.yaml` |
| **Service mesh telemetry** | Istio 1.21 — mTLS, Envoy access logs, L7 spans, mesh traffic dashboard | `observability/istio/`, `observability/grafana/dashboards/infrastructure/istio-traffic.json` |
| **Brand intelligence** | Social sentiment pipeline exposes 13 `social_*` Prometheus metrics; 3 Grafana Brand Intelligence dashboards | `social-sentiment/metrics/exporter.py`, `observability/grafana/dashboards/brand-intelligence/` |

Leadership-facing view: **Executive Health** dashboard (`observability/grafana/dashboards/platform-health/executive-health.json`) — SLO burn rates, RPS, P99, volume.

---

### 2. Incident response and runbook processes

Five runbooks covering the most common production failure modes:

| Runbook | Trigger alert | First action |
|---|---|---|
| [`api-outage.md`](observability/runbooks/api-outage.md) | `APIHigh5xxRateCritical` | Open Incident Triage dashboard |
| [`queue-lag.md`](observability/runbooks/queue-lag.md) | `SQSQueueDepthCritical` | Check consumer pod status |
| [`wallet-anomaly.md`](observability/runbooks/wallet-anomaly.md) | `WalletTransferFailureSpike` | Financial protocol — notify payments lead |
| [`collector-failure.md`](observability/runbooks/collector-failure.md) | `OTELCollectorDown` | Check collector pod logs |
| [`canary-regression.md`](observability/runbooks/canary-regression.md) | Post-deploy k6 failure | Run rollback decision tree |

All alert annotations in `observability/prometheus/rules/` link to the corresponding runbook via `annotations.runbook`.

---

### 3. Code reviews with production observability focus

The CI pipeline enforces observability contracts automatically on every PR:

| Gate | What it checks | Proof |
|---|---|---|
| `instrumentation-check` job | Every `src/services/*.ts` file must import from `telemetry/metrics` or `telemetry/tracer` — CI fails if missing | `.github/workflows/ci.yml` lines 42–73 |
| OTEL resource attribute check | `SEMRESATTRS_SERVICE_NAME` and `SEMRESATTRS_DEPLOYMENT_ENVIRONMENT` must be set in `tracer.ts` | `.github/workflows/ci.yml` lines 60–66 |
| `trace_id` in error responses | `src/app.ts` must include `trace_id` in error response shape | `.github/workflows/ci.yml` lines 68–72 |
| Prometheus rule validation | `promtool check rules` runs on all alert rule YAML files | `.github/workflows/ci.yml` lines 91–101 |
| Dashboard JSON validation | All Grafana dashboard JSON must be valid and contain `uid`, `title`, `tags` | `.github/workflows/ci.yml` lines 111–139 |

---

### 4. CI/CD pipeline development

Five GitHub Actions workflows:

| Workflow | Trigger | Key gates |
|---|---|---|
| `ci.yml` | PR / push to master or dev | Lint → typecheck → instrumentation check → observability config validation → unit tests (≥65% coverage) |
| `deploy.yml` | Push to master | Build → staging → prod + k6 post-deploy gate (blocks on failure) + SLO burn-rate check + Grafana deploy annotation |
| `observability-deploy.yml` | Changes to `observability/` or `terraform/` | Terraform plan/apply → dashboard push via Grafana API → PrometheusRules + Istio CRD apply |
| `synthetic-monitoring.yml` | Schedule every 5 minutes | `y_eet-synth smoke` → login flow + bet placement dry-run → Slack alert on failure |
| `social-sentiment.yml` | Changes to `social-sentiment/` | Ruff lint → 6 test suites (≥70% coverage) → metrics contract + schema + keyword config validation → Docker build → GHCR push |

---

### 5. Synthetic traffic generator — y_eet-synth (Go)

`y_eet-synth` is a purpose-built Go CLI that drives synthetic traffic, validates Istio mesh policies, injects fault scenarios, and gates canary rollouts.

**Commands**

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

**Traffic profiles**

| Profile | Concurrency | RPS | Duration | Notes |
|---|---|---|---|---|
| smoke | 5 | 5 | 30 s | CI post-deploy gate |
| low | 5 | 10 | 120 s | |
| normal | 20 | 50 | 300 s | |
| burst | 80 | 200 | 180 s | 4× burst every 30 s for 15 s |
| chaos | 15 | 30 | 180 s | fault injection enabled |
| mesh | 10 | 20 | 120 s | mesh validation enabled |
| canary | 10 | 25 | 120 s | canary + mesh validation |
| onboarding | 150 | 200 | 300 s | 55% registration funnel |
| flood | 300 | 500 | 600 s | 5× burst — load test only |

**Architecture** (`y_eet-synth/internal/`): `config` → `profiles` → `runner` (token-bucket rate limiter + goroutine pool) → `scenarios` (weighted picker) → `client` (HTTP with Envoy header capture) → `evaluator` → `reporter` (stdout + JSON).

**Exit codes:** 0 pass · 1 fail · 2 warn · 3 insufficient data — consumed directly by CI.

---

### 6. Distributed systems on AWS

| Component | AWS service | Notes |
|---|---|---|
| Compute | EKS 1.29 + Karpenter | Node autoscaling; pod scheduling in `betting` and `wallet` namespaces |
| Object storage | S3 Standard → Glacier IR lifecycle | Prometheus blocks, Loki chunks, Tempo traces |
| Queue | SQS + DLQ | Settlement async processing; `SQSDeadLetterQueueGrowing` alert fires on any DLQ message |
| Database | RDS (PostgreSQL) | Managed; metrics via CloudWatch Exporter |
| Cache | ElastiCache | Metrics via CloudWatch Exporter |
| Secrets | AWS Secrets Manager + IRSA | No static credentials in pod specs |
| Container registry | GHCR | Built and pushed by `social-sentiment.yml` and `deploy.yml` |

---

### 7. Mentoring junior engineers

The `observability/README.md` contains a step-by-step **Adding a New Service** checklist (7 steps: instrument → resource attributes → RED metrics → dashboard → SLO → runbook → synthetic check). Each step references the exact file to copy or extend, making it actionable without senior guidance.

---

## Required Skills

| Skill | Status | Proof |
|---|---|---|
| **Linux scripting** | Delivered | `scripts/demo.sh` (200-line Bash with preflight, wait loops, process management), `social-sentiment/scripts/run_pipeline.sh` |
| **Python** | Delivered | Entire `social-sentiment/` subsystem — scraper, NLP, pipeline, alerts, metrics, dashboard, 6 test suites |
| **JavaScript / TypeScript** | Delivered | `src/` — Fastify 4 API, full business logic, typed repositories, OTEL SDK |
| **Go** | Delivered | `y_eet-synth/` — full Go CLI: cobra commands, token-bucket rate limiter, concurrent runner, Istio mesh validator, chaos injector, canary split checker, JSON report output |
| **Terraform** | Delivered | `terraform/` — modular, remote state, OIDC, separate prod/staging root modules |
| **CDK / CloudFormation** | Not demonstrated | Terraform used exclusively for IaC |
| **Microservice architecture** | Delivered | API (Node) + social-sentiment (Python) as separate containers with independent metrics endpoints, tracing namespaces, and Docker Compose services |
| **CI/CD pipeline development** | Delivered | 5 GitHub Actions workflows with lint, test, build, deploy, synthetic, and SLO gates |
| **Observability and monitoring** | Delivered | Full OTEL + Prometheus + Grafana + Loki + Tempo + Alertmanager + Thanos stack |
| **Incident response and troubleshooting** | Delivered | 5 runbooks in `observability/runbooks/`; Incident Triage dashboard; severity model with PagerDuty + Slack routing |

---

## One-Command Demo

```bash
./scripts/demo.sh
```

Starts the entire stack, seeds Brand Intelligence demo data, runs synthetic traffic, and opens Grafana dashboards automatically. See the root `README.md` for full usage.
