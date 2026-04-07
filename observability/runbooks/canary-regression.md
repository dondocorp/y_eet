# Runbook: Canary Regression / Post-Deploy Failure

**Severity:** P1 (blocks deployment)  
**Trigger:** GitLab CI post-deploy validation k6 check fails, or `SLO_BetPlacement_FastBurn` fires within 15m of deploy  
**Dashboard:** [Deployment Health](/d/deployment-health) | [Incident Triage](/d/incident-triage)

---

## Automatic Detection Sources

1. **GitLab CI** — `post-deploy-validation` k6 job fails → pipeline blocked, deploy halted
2. **Grafana alert** — SLO burn rate spikes within 15m of a Grafana deployment annotation
3. **Synthetic checks** — `bet-placement-dryrun` or `login-flow` fail after deploy

---

## Immediate Actions (0–3 min)

### Check what was deployed
```bash
# See recent deployments
kubectl rollout history deployment/<service> -n <namespace>

# View the specific change
git log --oneline origin/main~1..origin/main
```

### Check the canary/post-deploy failure
```bash
# GitLab CI job logs
# Go to pipeline → post-deploy-validation job → check which check failed

# Or run locally
k6 run observability/k6/checks/post-deploy-validation.js \
  -e BASE_URL=https://api.y_eet.com \
  -e SYNTH_EMAIL=$SYNTH_EMAIL \
  -e SYNTH_PASSWORD=$SYNTH_PASSWORD
```

### Identify the blast radius
```promql
# Error rate after deploy (compare before vs after deploy timestamp)
sum(rate(istio_requests_total{destination_service_name="<service>", response_code=~"5.."}[5m]))

# Was it a latency regression?
histogram_quantile(0.99, sum(rate(y_eet_bet_placement_duration_ms_bucket[5m])) by (le))
```

## Rollback Decision Tree

```
Post-deploy validation failed?
├── Health check failed → Rollback immediately
├── Auth check failed → Rollback immediately
├── Wallet check failed → Rollback immediately (financial risk)
├── Bet placement failed → Rollback immediately
└── Latency degraded > 50% → Rollback if sustained > 3m
```

## Rollback Execution

```bash
# Rollback service
kubectl rollout undo deployment/<service> -n <namespace>

# Verify rollback
kubectl rollout status deployment/<service> -n <namespace>

# Confirm recovery
kubectl get pods -n <namespace>

# Re-run post-deploy validation against rolled-back version
k6 run observability/k6/checks/post-deploy-validation.js \
  -e BASE_URL=$BASE_URL \
  -e SYNTH_EMAIL=$SYNTH_EMAIL \
  -e SYNTH_PASSWORD=$SYNTH_PASSWORD
```

## After Rollback

1. Post rollback annotation to Grafana:
   ```bash
   curl -X POST http://grafana.monitoring.svc.cluster.local:3000/api/annotations \
     -H "Content-Type: application/json" \
     -d '{"text":"Rollback: <service> to previous version","tags":["deploy","rollback"]}'
   ```
2. Mark GitLab pipeline as failed with explanation
3. Create regression ticket linking trace_id from failed synthetic check
4. Fix, test in staging, re-deploy with increased synthetic validation
