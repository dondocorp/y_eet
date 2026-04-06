# Runbook: Wallet Anomaly / Transfer Failures

**Severity:** P1  
**Alerts:** `WalletTransferFailureSpike`, `SLO_WalletRead_FastBurn`  
**Dashboard:** [Betting & Wallet Critical Operations](/d/betting-wallet) | [Incident Triage](/d/incident-triage)

---

## STOP: Financial Impact Protocol

If wallet transfer failures exceed 1% for > 2 minutes:
1. Notify engineering lead AND payments team lead immediately
2. Do NOT auto-retry failed wallet transactions without investigation
3. All actions must be logged with timestamps

---

## Immediate Triage (0–5 min)

```promql
# Error rate
sum(rate(yeet_wallet_transfers_total{status="error"}[5m]))
/
sum(rate(yeet_wallet_transfers_total[5m]))

# Which operation type is failing?
sum(rate(yeet_wallet_transfers_total{status="error"}[5m])) by (type)
# type: deposit, withdrawal, bet_reserve, bet_win, adjustment
```

### Check wallet service logs
```logql
{namespace="wallet"} |= "error" | json | level="error"
  | line_format "{{.timestamp}} trace={{.trace_id}} msg={{.message}}"
```

### Check for DB constraint violations
```logql
{namespace="wallet"} |= "23505" or |= "serialization" or |= "deadlock"
```

## Common Causes

### 1. Insufficient balance — not a bug
```promql
yeet_wallet_transfers_total{status="error", reason="insufficient_balance"}
```
Normal if rate is < 1%. Elevated rate means client is not checking balance before betting.

### 2. DB serialization failures (high concurrent writes)
Look for Postgres `ERROR 40001` (serialization_failure) in logs.  
**Fix:** Check if DB connection pool is exhausted; consider read replica for balance reads.

### 3. Idempotency key collision
```logql
{namespace="wallet"} |= "23505" |= "wallet_transactions_idempotency_key"
```
If growing — client is generating non-unique idempotency keys. Escalate to consuming team.

### 4. Negative balance detection
If `yeet_wallet_transfers_total{status="error", reason="balance_negative"}` fires:
- **STOP processing withdrawals and bet reserves immediately**
- Check `wallet_accounts` table for users with `balance < 0`
- This is a data integrity issue — escalate to engineering lead

## Verification Queries

```sql
-- Check recent failed transactions (connect via kubectl exec)
SELECT id, user_id, type, amount, status, metadata, created_at
FROM wallet_transactions
WHERE status = 'failed'
  AND created_at > NOW() - INTERVAL '30 minutes'
ORDER BY created_at DESC
LIMIT 50;

-- Check for negative balances
SELECT user_id, balance, reserved
FROM wallet_accounts
WHERE balance::numeric < 0
   OR reserved::numeric < 0;
```

## Escalation

| Condition | Action |
|---|---|
| Any negative balance found | P1 — engineering lead + compliance immediately |
| Failure rate > 5% sustained | P1 — payments team oncall |
| Idempotency collision spike | Escalate to team producing the requests |
| Unknown cause after 15 min | Escalate + consider disabling withdrawals |
