# Runbook: OTEL Collector Failure

**Severity:** P2  
**Alerts:** `OTELCollectorDown`, `OTELCollectorDroppingSpans`, `OTELCollectorQueueFull`  
**Dashboard:** [Infra / Runtime](/d/infra-runtime)

---

## Impact Assessment

| Failure | Impact |
|---|---|
| DaemonSet pod down on node | Loss of traces/metrics from pods on that node |
| Gateway deployment down | All traces lost; metrics still scrape-based |
| Loki exporter backlogged | Log delivery delay; no data loss if buffer holds |
| Tempo unreachable | Traces dropped at tail sampler |

---

## Immediate Triage

```bash
# Check collector pod status
kubectl get pods -n monitoring -l app.kubernetes.io/name=opentelemetry-collector

# Check collector logs
kubectl logs -n monitoring -l app.kubernetes.io/name=opentelemetry-collector --tail=100

# Check collector self-metrics (port 8888)
kubectl port-forward -n monitoring svc/otel-daemonset-collector 8888:8888
curl -s localhost:8888/metrics | grep otelcol_
```

### Key self-metrics to check
```promql
# Span drop rate
rate(otelcol_processor_dropped_spans_total[5m])

# Exporter send failures
rate(otelcol_exporter_send_failed_spans_total[5m])

# Queue depth
otelcol_exporter_queue_size / otelcol_exporter_queue_capacity

# Memory usage
otelcol_process_memory_rss
```

## Remediation

### Pod OOMKilled — increase memory limit
```bash
# Check if OOMKilled
kubectl describe pod <otel-pod> -n monitoring | grep -A5 "Last State"

# Patch memory limit (temporary)
kubectl set resources daemonset/otel-daemonset -n monitoring \
  --limits=memory=600Mi --requests=memory=150Mi
```

### Exporter backlog — destination unreachable
```bash
# Check Tempo reachability
kubectl exec -n monitoring <otel-gateway-pod> -- \
  curl -v tempo.monitoring.svc.cluster.local:4317

# Check Loki reachability
kubectl exec -n monitoring <otel-gateway-pod> -- \
  curl -v http://loki-gateway.monitoring.svc.cluster.local/ready

# Check Prometheus remote write
kubectl exec -n monitoring <otel-gateway-pod> -- \
  curl -v http://prometheus-operated.monitoring.svc.cluster.local:9090/-/ready
```

### Restart collector
```bash
kubectl rollout restart daemonset/otel-daemonset -n monitoring
kubectl rollout restart deployment/otel-gateway -n monitoring
kubectl rollout status daemonset/otel-daemonset -n monitoring
```

## Escalation

If collector is down for > 10 minutes:
- Notify team that traces are unavailable for that window
- Document the time range in the incident timeline
- Check S3 WAL for any recoverable trace data from Tempo

Collector failures do NOT affect application availability — app still serves requests.
The risk is blind spots in observability during the outage window.
