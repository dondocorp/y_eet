# Yeet Observability Platform

Full-stack, open-source observability for a production iGaming platform. Traces, metrics, logs, dashboards, SLOs, synthetic checks, and incident runbooks — all in one place, all provisioned from this directory.

---

## Stack

| Concern | Tool | Why |
|---|---|---|
| **Traces** | Grafana Tempo (S3) | Free, TraceQL, native Grafana integration, S3 object store |
| **Metrics** | Prometheus + Thanos | HA, long-term S3 storage, compatible with everything |
| **Logs** | Grafana Loki (S3) | No full-text index = cheap at scale, LogQL, Grafana-native |
| **Dashboards** | Grafana OSS 10.x | Single portal for all signals, RBAC, dashboard-as-code |
| **Alerting** | Prometheus Alertmanager + Grafana Unified | PromQL alerts, routing, inhibition, PagerDuty + Slack |
| **Synthetic checks** | Grafana k6 + Blackbox Exporter | Scripted flows (login, bet placement) + endpoint probing |
| **Log shipping** | Fluent Bit (DaemonSet) | Lightweight, K8s-aware, Loki output |
| **Telemetry collection** | OTEL Collector (DaemonSet + Gateway) | Vendor-neutral, tail sampling, attribute enrichment |
| **Service mesh** | Istio 1.21 | mTLS, L7 telemetry, access logs, tracing, service map |
| **AWS integration** | CloudWatch Exporter | RDS, SQS, ElastiCache metrics → Prometheus |
| **Long-term storage** | S3 Standard → Glacier IR (lifecycle) | Near-instant retrieval, ~$0.004/GB/month |

---

## Directory Structure

```
observability/
│
├── collector/
│   ├── otelcol-daemonset.yaml    # Node-level: OTLP receive, Prometheus scrape, K8s attributes
│   ├── otelcol-gateway.yaml      # Cluster-level: tail-based sampling, route to Tempo/Loki/Prometheus
│   └── otelcol-local.yaml        # Local dev: used by docker-compose
│
├── istio/
│   ├── telemetry.yaml            # Telemetry CRs — sampling rates per namespace, access log filter, custom tags
│   ├── peer-authentication.yaml  # mTLS STRICT mesh-wide + scraper exemptions
│   └── mesh-config-patch.yaml    # Global meshconfig — JSON access log format, tracing endpoint
│
├── prometheus/
│   ├── prometheus-local.yaml     # Local dev scrape config
│   └── rules/
│       ├── latency-errors.yaml   # P99 latency, 5xx error rate, auth failures, risk circuit breaker
│       ├── slo-burn-rate.yaml    # Multi-window burn rate alerts (fast/slow) + SLO recording rules
│       └── queue-infra.yaml      # SQS depth, DLQ, consumer stall, pod crashloop, node/PVC pressure
│
├── alertmanager/
│   ├── alertmanager.yaml         # Production: PagerDuty + Slack routing, inhibition, grouping
│   ├── alertmanager-local.yaml   # Local dev: null receiver
│   └── templates.tmpl            # Slack message templates with runbook + dashboard links
│
├── loki/
│   ├── loki-config.yaml          # Production: S3 backend, 31d hot, TSDB schema v13
│   ├── loki-local.yaml           # Local dev: filesystem backend
│   └── fluent-bit-daemonset.yaml # DaemonSet + ConfigMap — tails pods, enriches K8s metadata, ships to Loki
│
├── tempo/
│   ├── tempo-config.yaml         # Production: S3 backend, metrics-generator (service graph + span metrics)
│   └── tempo-local.yaml          # Local dev: filesystem backend
│
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/          # Prometheus (Thanos), Loki, Tempo, CloudWatch — with trace↔log linking
│   │   └── dashboards/           # Folder definitions for dashboard-as-code
│   └── dashboards/
│       ├── platform-health/
│       │   └── executive-health.json        # SLO burn rates, RPS, P99, volume, incidents
│       ├── services/
│       │   └── api-reliability.json         # RED metrics by route, synthetic probe status
│       ├── infrastructure/
│       │   └── istio-traffic.json           # Service mesh traffic, mTLS, response flags, service map
│       └── reliability/
│           ├── incident-triage.json         # On-call view: alerts, errors, latency, logs, service map
│           └── slo-error-budget.json        # Error budget burn rates, SLO compliance, latency SLOs
│
├── k6/
│   └── checks/
│       ├── login-flow.js             # Auth → wallet read → token refresh (every 1m)
│       ├── bet-placement-dryrun.js   # Login → $0.01 bet → verify retrieval (every 2m)
│       └── post-deploy-validation.js # Health → auth → wallet → bet → trace_id check (post-deploy)
│
├── synthetic/
│   ├── blackbox-config.yaml      # Production HTTP/TCP probe modules
│   └── blackbox-local.yaml       # Local dev probe modules
│
└── runbooks/
    ├── api-outage.md             # High 5xx rate — triage, rollback, escalation
    ├── queue-lag.md              # SQS backlog, DLQ, consumer stall — drain, replay, purge
    ├── wallet-anomaly.md         # Transfer failures, negative balance — financial protocol
    ├── collector-failure.md      # OTEL Collector down — impact, remediation, OOM
    └── canary-regression.md      # Post-deploy check failure — rollback decision tree
```

---

## Telemetry Architecture

### What comes from where

| Signal | Source | Do NOT duplicate |
|---|---|---|
| HTTP request count | Istio `istio_requests_total` | Do not use app `yeet_http_requests_total` for SLOs |
| HTTP request duration | Istio `istio_request_duration_milliseconds` | Do not create a competing histogram in app middleware |
| mTLS status, cert expiry | Istio + cert-manager | App has no visibility here |
| Service-to-service errors | Istio (response_code label) | App emits business error context only |
| Business transaction traces | App OTEL SDK | Istio emits only L7 spans per hop |
| Business domain metrics | App OTEL SDK | Bet amounts, wallet deltas, risk scores |
| Structured app logs | App stdout → Fluent Bit → Loki | Separate stream from Istio access logs |
| Istio access logs | Envoy stdout → Fluent Bit → Loki | Label `job=istio-access-log` — do not merge with app logs |

### Trace propagation

```
Client request
  → Ingress (Istio generates root span)
    → app HTTP handler (OTEL SDK continues span)
      → BetService.placeBet (tracer.startActiveSpan creates child span)
        → RiskService.evaluate (pg auto-instrumentation creates db child span)
        → WalletService.reserveForBet (pg span)
      → response (trace_id echoed in response body)
```

All spans carry `traceparent` (W3C) headers. Istio configured to forward to OTEL Collector Gateway via Zipkin protocol. Gateway applies tail-based sampling before writing to Tempo.

### Sampling policy (OTEL Gateway)

| Rule | Action |
|---|---|
| `status_code = ERROR` | Always sample |
| `latency > 1000ms` | Always sample |
| `synthetic.check = true` | Always sample |
| `service.name in [bet-svc, settlement-svc]` | Always sample |
| Everything else | 10% probabilistic |

Istio namespace overrides: `betting` and `wallet` namespaces → 100% sampling at the sidecar level.

### Log correlation

Every log line includes `trace_id` as a JSON field (not a Loki label). Grafana Loki datasource is configured with a derived field regex `"trace_id":"([a-f0-9]{32})"` → links directly to Tempo trace. One click from error log → full distributed trace.

---

## Dashboards

### Portal structure

```
Grafana
├── Platform Health
│   ├── Executive Health          — SLO burn rates, RPS, P99, volume (leadership view)
│   ├── Global Platform Overview  — all services, deployment frequency
│   └── SLO / Error Budget        — burn rates, latency SLOs, 30d compliance
│
├── Services
│   ├── API Reliability           — RED by route, rate limits, synthetic probes
│   ├── Auth & Session            — token issuance, failures, refresh rate
│   ├── Wallet & Ledger           — transfer rates, latency, idempotency hits
│   ├── Betting & Settlement      — placement pipeline, volume, idempotency anomalies
│   ├── Game Sessions             — active sessions, lifecycle events
│   └── Fraud & Risk              — evaluation rates, circuit breaker, flag distribution
│
├── Infrastructure
│   ├── Service Mesh / Istio      — mesh traffic, mTLS, response flags, service map
│   ├── Queue & Async             — SQS depth, DLQ, consumer throughput
│   ├── Infra / Runtime           — nodes, pods, PVCs, crashloops
│   └── AWS Managed Services      — RDS, ElastiCache, SQS via CloudWatch
│
└── Reliability
    ├── Incident Triage           — alerts panel, errors by service, logs, service map
    ├── Deployment Health         — deploy annotations, error rate before/after, rollback status
    └── Synthetic Monitoring      — k6 check results, Blackbox probe status, post-deploy gates
```

### Dashboard naming convention

```
File:   {folder}-{service-or-scope}-{purpose}.json
Title:  [SCOPE] Service/Component — Purpose
Panel:  {MetricType}: {Description}

Examples:
  services-betting-reliability.json
  [SERVICE] Betting — Reliability
  P99 Latency: Bet Placement End-to-End
```

---

## Alerting

### Severity model

| Severity | Meaning | Pages? | Channel |
|---|---|---|---|
| `critical` + `page: true` | Revenue/availability impact, requires immediate human action | Yes (PagerDuty) | `#alerts-critical` |
| `critical` | Serious degradation, high urgency | No (Slack only) | `#alerts-critical` |
| `warning` | Elevated risk, needs attention soon | No | `#alerts-warnings` |

### Key alert rules

| Alert | Trigger | Source |
|---|---|---|
| `BetPlacementP99LatencyCritical` | P99 > 2000ms for 2m | App histogram |
| `APIHigh5xxRateCritical` | 5xx > 5% for 1m | Istio |
| `BetServiceHighErrorRate` | bet-svc 5xx > 2% for 2m | Istio |
| `AuthHighFailureRateCritical` | Auth failure rate > 30% | App counter |
| `SLO_BetPlacement_FastBurn` | Burn rate > 14.4x (1h window) | Recording rule |
| `SLO_Auth_FastBurn` | Burn rate > 14.4x (1h window) | Recording rule |
| `WalletTransferFailureSpike` | Wallet error rate > 5% | App counter |
| `SQSDeadLetterQueueGrowing` | DLQ has any messages | CloudWatch exporter |
| `OTELCollectorDown` | Collector unreachable | Prometheus `up` |
| `IstioMTLSCertExpiryCritical` | Cert expires in < 3 days | cert-manager metrics |
| `IstioUnexpectedServiceToServiceFailure` | s2s 5xx > 0.5 rps | Istio |

### Inhibition rules

- Critical from service X suppresses warnings from service X
- `NodeDown` suppresses service-level alerts from that node (infra root cause)
- `MaintenanceWindowActive` suppresses all SLO burn-rate alerts

---

## SLOs

| SLO | SLI | Target | Window | Source |
|---|---|---|---|---|
| Auth availability | `(non-5xx requests) / total` | 99.9% | 30d | App metrics |
| Bet placement availability | `(non-5xx requests) / total` | 99.5% | 30d | Istio |
| Bet placement P99 latency | `P99 < 500ms` | 99% of requests | 30d | App histogram |
| Wallet read availability | `(non-5xx requests) / total` | 99.9% | 30d | Istio |
| Observability pipeline health | Collector `up` + no span drops | 99.5% | 30d | Prometheus |

Burn-rate alerts use two-window detection (fast: 1h at 14.4x, slow: 6h at 6x) to catch both sudden spikes and slow leaks.

---

## Synthetic Monitoring

| Check | Cadence | Covers | Fail action |
|---|---|---|---|
| `login-flow` | Every 5m (GitHub Actions schedule) | Auth → wallet read → token refresh | Slack alert |
| `bet-placement-dryrun` | Every 10m | Login → $0.01 bet → bet retrieval | Slack alert |
| `post-deploy-validation` | On every deploy | Health → auth → wallet → bet → trace_id | Blocks deploy |
| Blackbox `/health/live` | Every 15s (Prometheus scrape) | Liveness endpoint | Alert: `probe_success == 0` |
| Blackbox `/health/ready` | Every 15s | Readiness endpoint | Alert: `probe_success == 0` |

All synthetic requests carry `X-Synthetic: true` → tagged in metrics, logs, and traces. Filterable everywhere. Istio triggers 100% sampling on synthetic traffic.

---

## Runbooks

| Runbook | Trigger alert | First action |
|---|---|---|
| [`api-outage.md`](runbooks/api-outage.md) | `APIHigh5xxRateCritical` | Open Incident Triage dashboard |
| [`queue-lag.md`](runbooks/queue-lag.md) | `SQSQueueDepthCritical`, `SQSConsumerNotConsuming` | Check consumer pod status |
| [`wallet-anomaly.md`](runbooks/wallet-anomaly.md) | `WalletTransferFailureSpike` | Financial protocol — notify payments lead |
| [`collector-failure.md`](runbooks/collector-failure.md) | `OTELCollectorDown` | Check collector pod logs |
| [`canary-regression.md`](runbooks/canary-regression.md) | Post-deploy k6 failure | Run rollback decision tree |

---

## GitHub Actions Integration

| Workflow | Trigger | Observability gates |
|---|---|---|
| `ci.yml` | PR / push | Instrumentation contract check, OTEL config validation, Prometheus rule validation, Alertmanager config check, dashboard JSON validation |
| `deploy.yml` | Push to master | k6 post-deploy validation (blocks on failure), SLO burn-rate check (advisory), Grafana annotation on every deploy |
| `observability-deploy.yml` | Changes to `observability/` or `terraform/` | Terraform plan/apply, dashboard push via Grafana API, PrometheusRules + Istio CRD apply |
| `synthetic-monitoring.yml` | Schedule (every 5m) | Login flow + bet placement dry-run, Slack alert on failure |

---

## Local Development

Everything runs in Docker Compose:

```bash
docker compose up
```

| Service | URL |
|---|---|
| API | http://localhost:8080 |
| Prometheus metrics | http://localhost:9464/metrics |
| Grafana | http://localhost:3000 (anonymous admin) |
| Prometheus | http://localhost:9090 |
| Tempo | http://localhost:3200 |
| Loki | http://localhost:3100 |
| Alertmanager | http://localhost:9093 |
| Blackbox Exporter | http://localhost:9115 |

Grafana auto-provisions all datasources and dashboards from `observability/grafana/`. No manual setup required.

---

## Adding a New Service

1. **Instrument the service** — import from `../telemetry/metrics` and `../telemetry/tracer`. The CI `instrumentation-check` job will fail if you don't.
2. **Add resource attributes** — ensure `service.name`, `service.version`, and `deployment.environment` are set (inherited from the OTEL SDK resource in `tracer.ts`).
3. **Define RED metrics** — at minimum: request counter, error counter, latency histogram.
4. **Add a dashboard** — copy `services/api-reliability.json` as a template. Push to `observability/grafana/dashboards/services/`.
5. **Add an SLO** — add recording rules to `prometheus/rules/slo-burn-rate.yaml` following the existing pattern.
6. **Add a runbook** — copy an existing runbook template into `runbooks/`. Link it from alert `annotations.runbook`.
7. **Add a synthetic check** — add a k6 script to `k6/checks/` and wire it into `synthetic-monitoring.yml`.
