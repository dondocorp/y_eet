# Runbook: API Outage / High 5xx Rate

**Severity:** P1/P2  
**Alert:** `APIHigh5xxRateCritical` / `BetServiceHighErrorRate`  
**Dashboard:** [Incident Triage](/d/incident-triage) | [API Reliability](/d/api-reliability) | [Istio Traffic](/d/istio-traffic)

---

## Immediate Actions (0–5 min)

1. **Open [Incident Triage Dashboard](/d/incident-triage)** — check which services have elevated 5xx.
2. **Check firing alerts panel** for co-firing alerts (pod crashloop, node memory, DB down).
3. **Check recent deployments panel** — was a deploy in the last 30 min? If yes → [consider rollback](#rollback).
4. **Check request volume** — is traffic present? If RPS dropped to 0, the issue may be ingress/DNS.

## First 15 Minutes

### Identify blast radius
```
# Which services have 5xx?
sum(rate(istio_requests_total{response_code=~"5.."}[5m])) by (destination_service_name)

# Is it a single pod or the entire deployment?
kube_pod_container_status_restarts_total{namespace=~"auth|wallet|betting|game|fraud"}
```

### Check pod health
```bash
kubectl get pods -n betting          # look for CrashLoopBackOff, OOMKilled, Pending
kubectl describe pod <pod-name> -n betting   # check Events section
kubectl logs <pod-name> -n betting --tail=100 --previous
```

### Check Loki error logs
In Grafana Explore → Loki:
```logql
{namespace="betting"} |= "error" | json | level="error" | line_format "{{.timestamp}} {{.trace_id}} {{.message}}"
```

### Check for DB issues
```bash
# Postgres connection pool exhaustion
kubectl exec -n default <api-pod> -- node -e "require('./dist/db/pool').pool.totalCount"

# CloudWatch → RDS → DatabaseConnections metric spike?
```

### Check Istio mesh errors
In Grafana → Istio Traffic dashboard:
- Response flags `UF` (upstream connect failure) → service not accepting connections
- Response flags `URX` (upstream retry exhausted) → downstream overwhelmed
- Response flags `DC` (downstream connection termination) → client closed connections

## First 60 Minutes

### Trace a specific failing request
1. From error logs, copy `trace_id`
2. Go to Grafana Explore → Tempo → paste trace_id
3. Look for failed span, check `db.statement`, `error.message`, `http.status_code` attributes

### Check DB / dependency health
```bash
kubectl exec -n default <api-pod> -- curl -s http://localhost:8080/health/dependencies | jq .
```

### Check SQS queues (if async processing involved)
In Grafana → Queue Dashboard: look for DLQ growth or consumer stall.

## Rollback
```bash
# Check current deployment revision
kubectl rollout history deployment/bet-svc -n betting

# Roll back to previous
kubectl rollout undo deployment/bet-svc -n betting

# Monitor recovery
watch -n 5 'kubectl get pods -n betting'
```

## Escalation

| Condition | Action |
|---|---|
| 5xx > 5% for 10+ min | Escalate to engineering lead |
| Wallet or auth down | Escalate immediately — revenue/access impact |
| Unknown root cause after 30 min | Engage DBA + SRE lead |
| Mass user impact confirmed | Open P1 incident, notify product |

## Post-Incident

- File postmortem within 48h
- Link timeline: Grafana annotation → incident channel
- Add regression alert if root cause wasn't covered
