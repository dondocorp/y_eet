# Observability Platform

> Full-stack observability for the Yeet crypto-casino platform. Traces, metrics, logs, dashboards,
> SLOs, synthetic checks, and incident runbooks — all provisioned from this directory.

---

## Stack

| Concern | Tool | Rationale |
|---|---|---|
| **Traces** | Grafana Tempo (S3 backend) | TraceQL, native Grafana integration, cost-efficient object storage |
| **Metrics** | Prometheus + Thanos | HA, 13-month S3 long-term storage, universal ecosystem compatibility |
| **Logs** | Grafana Loki (S3 backend) | No full-text index keeps costs low at scale; LogQL; Grafana-native |
| **Dashboards** | Grafana OSS 10.x | Single portal for all signals, RBAC, dashboard-as-code via provisioning |
| **Alerting** | Prometheus Alertmanager + Grafana Unified | PromQL alerts, inhibition rules, PagerDuty + Slack routing |
| **Synthetic checks** | k6 + Blackbox Exporter | Scripted user flows (login, bet placement) + passive endpoint probing |
| **Log shipping** | Fluent Bit DaemonSet | Lightweight, Kubernetes-native, direct Loki output |
| **Telemetry collection** | OTEL Collector (DaemonSet + Gateway) | Vendor-neutral, tail-based sampling, attribute enrichment |
| **Service mesh** | Istio 1.21 | mTLS, L7 telemetry, access logs, distributed tracing, service map |
| **AWS integration** | CloudWatch Exporter | Bridges RDS, SQS, and ElastiCache metrics into Prometheus |
| **Long-term storage** | S3 Standard → Glacier IR lifecycle | Near-instant retrieval at ~$0.004/GB/month |

---

## Telemetry Architecture

### Signal Ownership

Understanding which layer owns which metric prevents duplication and query confusion:

| Signal | Authoritative Source | Notes |
|---|---|---|
| HTTP request count | `istio_requests_total` | Use for SLOs — do not use app `y_eet_http_requests_total` |
| HTTP request duration | `istio_request_duration_milliseconds` | Istio sidecar histogram is the SLO source of truth |
| mTLS status, cert expiry | Istio + cert-manager | App has no visibility into mesh cert lifecycle |
| Service-to-service errors | Istio `response_code` label | App emits business-level error context only |
| Business transaction traces | App OTEL SDK | Istio emits only one L7 span per hop |
| Business domain metrics | App OTEL SDK | Bet amounts, wallet deltas, risk scores, idempotency hits |
| Structured app logs | App stdout → Fluent Bit → Loki | Separate Loki stream from Istio access logs |
| Istio access logs | Envoy stdout → Fluent Bit → Loki | Label: `job=istio-access-log` — do not merge with app logs |

### Trace Propagation

```
Client request
  → Istio Ingress Gateway          (generates root span)
    → Fastify HTTP handler          (OTEL SDK continues span via traceparent header)
      → BetService.placeBet         (tracer.startActiveSpan creates child span)
        → RiskService.evaluate      (pg auto-instrumentation creates db child span)
        → WalletService.reserveForBet
      → HTTP response               (trace_id echoed in response body)
```

All spans carry W3C `traceparent` headers. Istio forwards traces to the OTEL Collector Gateway via Zipkin. The Gateway applies tail-based sampling before writing to Tempo.

### Sampling Policy

| Rule | Action |
|---|---|
| `status_code = ERROR` | Always sample |
| `latency > 1000ms` | Always sample |
| `synthetic.check = true` | Always sample |
| `service.name` in `[bet-svc, settlement-svc]` | Always sample |
| All other traffic | 10% probabilistic |

Istio namespace overrides: `betting` and `wallet` namespaces → 100% sampling at the sidecar.

### Log → Trace Correlation

Every structured log line includes `trace_id` as a JSON field. The Grafana Loki datasource uses a derived field regex — `"trace_id":"([a-f0-9]{32})"` — to link directly to Tempo. One click from an error log opens the full distributed trace.

---

## Directory Structure

```
observability/
├── collector/
│   ├── otelcol-daemonset.yaml      # Node-level: OTLP receive, Prometheus scrape, K8s attributes
│   ├── otelcol-gateway.yaml        # Cluster-level: tail sampling, route to Tempo/Loki/Prometheus
│   └── otelcol-local.yaml          # Local dev: used by docker-compose
│
├── istio/
│   ├── telemetry.yaml              # Telemetry CRs — sampling rates per namespace, access log filter
│   ├── peer-authentication.yaml    # mTLS STRICT mesh-wide + scraper exemptions
│   └── mesh-config-patch.yaml      # Global meshconfig — JSON access log format, tracing endpoint
│
├── prometheus/
│   ├── prometheus-local.yaml       # Local dev scrape config
│   └── rules/
│       ├── latency-errors.yaml     # P99 latency, 5xx rate, auth failures, risk circuit breaker
│       ├── slo-burn-rate.yaml      # Multi-window burn rate alerts + SLO recording rules
│       └── queue-infra.yaml        # SQS depth, DLQ, consumer stall, crashloops, node/PVC pressure
│
├── alertmanager/
│   ├── alertmanager.yaml           # Production: PagerDuty + Slack routing, inhibition, grouping
│   ├── alertmanager-local.yaml     # Local dev: null receiver
│   └── templates.tmpl              # Slack message templates with runbook + dashboard links
│
├── loki/
│   ├── loki-config.yaml            # Production: S3 backend, 31d hot retention, TSDB schema v13
│   ├── loki-local.yaml             # Local dev: filesystem backend
│   └── fluent-bit-daemonset.yaml   # DaemonSet + ConfigMap — tails pods, enriches K8s metadata
│
├── tempo/
│   ├── tempo-config.yaml           # Production: S3 backend, metrics-generator (service graph + spans)
│   └── tempo-local.yaml            # Local dev: filesystem backend
│
├── grafana/
│   ├── provisioning/
│   │   ├── datasources/            # Prometheus (Thanos), Loki, Tempo, CloudWatch — trace↔log linking
│   │   └── dashboards/             # Folder definitions for dashboard-as-code provisioning
│   └── dashboards/
│       ├── platform-health/
│       │   └── executive-health.json         # SLO burn rates, RPS, P99, volume (leadership view)
│       ├── services/
│       │   └── api-reliability.json          # RED metrics by route, rate limits, synthetic probe status
│       ├── infrastructure/
│       │   └── istio-traffic.json            # Mesh traffic, mTLS, response flags, service map
│       └── reliability/
│           ├── incident-triage.json          # On-call: active alerts, errors, latency, logs
│           └── slo-error-budget.json         # Burn rates, SLO compliance, latency SLOs
│
├── k6/
│   └── checks/
│       ├── login-flow.js             # Auth → wallet read → token refresh
│       ├── bet-placement-dryrun.js   # Login → $0.01 bet → verify retrieval
│       └── post-deploy-validation.js # Health → auth → wallet → bet → trace_id check
│
├── synthetic/
│   ├── blackbox-config.yaml        # Production HTTP/TCP probe modules
│   └── blackbox-local.yaml         # Local dev probe modules
│
└── runbooks/
    ├── api-outage.md               # High 5xx rate — triage, rollback, escalation
    ├── queue-lag.md                # SQS backlog, DLQ, consumer stall — drain, replay, purge
    ├── wallet-anomaly.md           # Transfer failures, negative balance — financial protocol
    ├── collector-failure.md        # OTEL Collector down — impact, remediation, OOM
    └── canary-regression.md        # Post-deploy check failure — rollback decision tree
```

---

## Dashboards

### Portal Structure

```
Grafana
├── Platform Health
│   ├── Executive Health           SLO burn rates, RPS, P99, volume (leadership view)
│   ├── Global Platform Overview   All services, deployment frequency
│   └── SLO / Error Budget         Burn rates, latency SLOs, 30d compliance
│
├── Services
│   ├── API Reliability            RED metrics by route, rate limits, synthetic probes
│   ├── Auth & Session             Token issuance, failures, refresh rate
│   ├── Wallet & Ledger            Transfer rates, latency, idempotency hits
│   ├── Betting & Settlement       Placement pipeline, volume, idempotency anomalies
│   ├── Game Sessions              Active sessions, lifecycle events
│   └── Fraud & Risk               Evaluation rates, circuit breaker, flag distribution
│
├── Infrastructure
│   ├── Service Mesh / Istio       Mesh traffic, mTLS, response flags, service map
│   ├── Queue & Async              SQS depth, DLQ, consumer throughput
│   ├── Infra / Runtime            Nodes, pods, PVCs, crashloops
│   └── AWS Managed Services       RDS, ElastiCache, SQS via CloudWatch Exporter
│
├── Reliability
│   ├── Incident Triage            Alerts panel, errors by service, logs, service map
│   ├── Deployment Health          Deploy annotations, error rate before/after, rollback
│   └── Synthetic Monitoring       k6 check results, Blackbox probe status, post-deploy gates
│
└── Brand Intelligence
    ├── Executive View             KPI stats, 24h sentiment trend, alert history
    ├── Operations View            Real-time negative ratio, scraper health, live logs
    └── Pipeline Health            Classifier failures, relevance distribution, Tempo traces
```

### Dashboard Naming Convention

```
File:   {folder}-{service-or-scope}-{purpose}.json
Title:  [SCOPE] Service/Component — Purpose
Panel:  {MetricType}: {Description}

Example:
  services-betting-reliability.json
  [SERVICE] Betting — Reliability
  P99 Latency: Bet Placement End-to-End
```

---

## Alerting

### Severity Model

| Severity | Meaning | Pages? | Channel |
|---|---|---|---|
| `critical` + `page: true` | Revenue or availability impact — immediate human action required | Yes (PagerDuty) | `#alerts-critical` |
| `critical` | Serious degradation, high urgency | No | `#alerts-critical` |
| `warning` | Elevated risk, needs attention soon | No | `#alerts-warnings` |

### Key Alert Rules

| Alert | Trigger | Source |
|---|---|---|
| `BetPlacementP99LatencyCritical` | P99 > 2000ms for 2m | App histogram |
| `APIHigh5xxRateCritical` | 5xx > 5% for 1m | Istio |
| `BetServiceHighErrorRate` | bet-svc 5xx > 2% for 2m | Istio |
| `AuthHighFailureRateCritical` | Auth failure rate > 30% | App counter |
| `SLO_BetPlacement_FastBurn` | Burn rate > 14.4× (1h window) | Recording rule |
| `SLO_Auth_FastBurn` | Burn rate > 14.4× (1h window) | Recording rule |
| `WalletTransferFailureSpike` | Wallet error rate > 5% | App counter |
| `SQSDeadLetterQueueGrowing` | DLQ has any messages | CloudWatch Exporter |
| `OTELCollectorDown` | Collector unreachable | Prometheus `up` |
| `IstioMTLSCertExpiryCritical` | Cert expires in < 3 days | cert-manager metrics |
| `IstioUnexpectedServiceToServiceFailure` | s2s 5xx > 0.5 rps | Istio |

### Inhibition Rules

- Critical alert from service X suppresses warnings from service X
- `NodeDown` suppresses service-level alerts from that node (infra root cause takes precedence)
- `MaintenanceWindowActive` suppresses all SLO burn-rate alerts

---

## SLOs

| SLO | SLI | Target | Window | Source |
|---|---|---|---|---|
| Auth availability | Non-5xx requests / total | 99.9% | 30d | App metrics |
| Bet placement availability | Non-5xx requests / total | 99.5% | 30d | Istio |
| Bet placement P99 latency | P99 < 500ms | 99% of requests | 30d | App histogram |
| Wallet read availability | Non-5xx requests / total | 99.9% | 30d | Istio |
| Observability pipeline health | Collector `up` + no span drops | 99.5% | 30d | Prometheus |

Burn-rate alerts use two-window detection — **fast burn** (1h at 14.4×) catches sudden spikes; **slow burn** (6h at 6×) catches gradual leaks — both trigger before meaningful error budget is consumed.

---

## Synthetic Monitoring

| Check | Cadence | Covers | On failure |
|---|---|---|---|
| `login-flow` | Every 5m (GitHub Actions schedule) | Auth → wallet read → token refresh | Slack alert |
| `bet-placement-dryrun` | Every 10m | Login → $0.01 bet → bet retrieval | Slack alert |
| `post-deploy-validation` | On every deploy | Health → auth → wallet → bet → `trace_id` check | Blocks deploy |
| Blackbox `/health/live` | Every 15s (Prometheus scrape) | Liveness endpoint | Alert: `probe_success == 0` |
| Blackbox `/health/ready` | Every 15s | Readiness endpoint | Alert: `probe_success == 0` |

All synthetic requests carry `X-Synthetic: true` — tagged in metrics, logs, and traces. Filterable everywhere. Istio triggers 100% trace sampling for synthetic traffic.

---

## Runbooks

| Runbook | Trigger alert | First action |
|---|---|---|
| [`api-outage.md`](runbooks/api-outage.md) | `APIHigh5xxRateCritical` | Open Incident Triage dashboard |
| [`queue-lag.md`](runbooks/queue-lag.md) | `SQSQueueDepthCritical`, `SQSConsumerNotConsuming` | Check consumer pod status |
| [`wallet-anomaly.md`](runbooks/wallet-anomaly.md) | `WalletTransferFailureSpike` | Financial protocol — notify payments lead |
| [`collector-failure.md`](runbooks/collector-failure.md) | `OTELCollectorDown` | Check collector pod logs |
| [`canary-regression.md`](runbooks/canary-regression.md) | Post-deploy k6 failure | Run rollback decision tree |

All alert `annotations.runbook` fields link directly to the corresponding runbook URL.

---

## CI/CD Integration

| Workflow | Trigger | Observability gates |
|---|---|---|
| `ci.yml` | PR / push | Instrumentation contract check, Prometheus rule validation (`promtool`), Alertmanager config check, dashboard JSON validation |
| `deploy.yml` | Push to master | k6 post-deploy validation (blocks on failure), SLO burn-rate check, Grafana deploy annotation |
| `observability-deploy.yml` | Changes to `observability/` or `terraform/` | Terraform plan/apply, dashboard push via Grafana API, PrometheusRules + Istio CRD apply |
| `synthetic-monitoring.yml` | Schedule (every 5m) | Login flow + bet placement dry-run, Slack alert on failure |

---

## Local Development

```bash
# Start the full stack (from repo root)
docker compose up
```

| Service | URL |
|---|---|
| Grafana | `http://localhost:3000` (anonymous admin) |
| Prometheus | `http://localhost:9090` |
| Tempo | `http://localhost:3200` |
| Loki | `http://localhost:3100` |
| Alertmanager | `http://localhost:9093` |
| Blackbox Exporter | `http://localhost:9115` |

Grafana auto-provisions all datasources and dashboards from `observability/grafana/`. No manual setup required.

---

## Adding a New Service

Follow this checklist when onboarding a new service to the observability platform:

1. **Instrument** — import from `../telemetry/metrics` and `../telemetry/tracer`. The CI `instrumentation-check` job fails if either import is missing.
2. **Resource attributes** — ensure `service.name`, `service.version`, and `deployment.environment` are set. These are inherited from the OTEL SDK resource configured in `tracer.ts`.
3. **RED metrics** — expose at minimum: a request counter, an error counter, and a latency histogram.
4. **Dashboard** — copy `dashboards/services/api-reliability.json` into `observability/grafana/dashboards/services/` and update `uid`, `title`, and metric selectors.
5. **SLO** — add recording rules and burn-rate alerts to `prometheus/rules/slo-burn-rate.yaml` following the existing pattern.
6. **Runbook** — copy an existing runbook template into `runbooks/`. Link it via `annotations.runbook` in the alert rule.
7. **Synthetic check** — add a k6 script to `k6/checks/` and wire it into `synthetic-monitoring.yml`.
