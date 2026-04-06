# Runbook: Queue Lag / SQS Backlog

**Severity:** P2/P3  
**Alerts:** `SQSQueueDepthHigh`, `SQSQueueDepthCritical`, `SQSDeadLetterQueueGrowing`, `SQSConsumerNotConsuming`  
**Dashboard:** [Queue & Async Processing](/d/queue-async)

---

## Immediate Triage (0–5 min)

1. **Open Queue Dashboard** — identify which queue(s) are lagging.
2. **Is the consumer running?**
   ```bash
   kubectl get pods -n <consumer-namespace> | grep <consumer-name>
   ```
3. **Is the DLQ growing?** — If yes, there are poison messages causing consumer failures.
4. **Is the queue depth growing or stable?** — Growing = consumer stalled. Stable high = caught in processing lag.

## Diagnose Consumer

```bash
# Check consumer logs for errors
kubectl logs -l app=<consumer> -n <namespace> --tail=200 | grep -i error

# Check consumer pod restarts
kubectl get pods -n <namespace> -o wide

# Check consumer metrics in Grafana
{namespace="<namespace>", app="<consumer>"} |= "error" | json
```

## DLQ Investigation

If `yeet-*-dlq` has messages:

```bash
# Peek at DLQ messages (AWS CLI)
aws sqs receive-message \
  --queue-url https://sqs.${AWS_REGION}.amazonaws.com/${ACCOUNT_ID}/${QUEUE_NAME}-dlq \
  --max-number-of-messages 10 \
  --attribute-names All \
  --message-attribute-names All

# Common causes:
# 1. Schema mismatch — consumer code version mismatch with producer
# 2. Missing idempotency key causing duplicate processing failure
# 3. Downstream dependency (DB/API) temporarily unavailable
```

## Remediation

### Consumer stalled — restart
```bash
kubectl rollout restart deployment/<consumer> -n <namespace>
kubectl rollout status deployment/<consumer> -n <namespace>
```

### Scale consumer to drain backlog
```bash
kubectl scale deployment/<consumer> --replicas=5 -n <namespace>
# Monitor queue depth drop in Grafana
# Scale back down after queue clears
kubectl scale deployment/<consumer> --replicas=2 -n <namespace>
```

### Replay DLQ messages
```bash
# Move messages from DLQ back to main queue for reprocessing
# (only after fixing the root cause)
aws sqs start-message-move-task \
  --source-arn arn:aws:sqs:${AWS_REGION}:${ACCOUNT_ID}:${QUEUE_NAME}-dlq \
  --destination-arn arn:aws:sqs:${AWS_REGION}:${ACCOUNT_ID}:${QUEUE_NAME}
```

### Purge DLQ (last resort — poison messages only)
```bash
# Only if messages are confirmed invalid/unrecoverable
aws sqs purge-queue \
  --queue-url https://sqs.${AWS_REGION}.amazonaws.com/${ACCOUNT_ID}/${QUEUE_NAME}-dlq
```

## Escalation

| Condition | Action |
|---|---|
| Settlement queue DLQ > 100 | Escalate to payments team immediately |
| Fraud/risk queue lagging > 10k | Risk decisions may be delayed — notify compliance |
| Consumer restart doesn't clear lag | Escalate to SRE lead |
