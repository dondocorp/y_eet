import { metrics } from '@opentelemetry/api';

const meter = metrics.getMeter('yeet-platform-api');

// ─── Auth metrics ─────────────────────────────────────────────────────────────
export const authTokensIssued = meter.createCounter('yeet_auth_tokens_issued_total', {
  description: 'Total number of JWT tokens issued',
});

export const authFailures = meter.createCounter('yeet_auth_failures_total', {
  description: 'Auth failures by reason (user_not_found, bad_password, account_suspended)',
});

export const authSessionRevocations = meter.createCounter('yeet_auth_session_revocations_total', {
  description: 'Total session revocations',
});

export const authRefreshTotal = meter.createCounter('yeet_auth_refresh_total', {
  description: 'Token refresh attempts by outcome (success, invalid, expired, reused)',
});

// ─── Bet metrics ──────────────────────────────────────────────────────────────
export const betPlacementsTotal = meter.createCounter('yeet_bet_placements_total', {
  description: 'Total bet placements by status and game',
});

export const betSettlementsTotal = meter.createCounter('yeet_bet_settlements_total', {
  description: 'Total bet settlements by outcome',
});

export const betPlacementDuration = meter.createHistogram('yeet_bet_placement_duration_ms', {
  description: 'Bet placement end-to-end latency in milliseconds',
  unit: 'ms',
  advice: { explicitBucketBoundaries: [10, 25, 50, 100, 200, 500, 1000, 2000, 5000] },
});

export const betSettlementDuration = meter.createHistogram('yeet_bet_settlement_duration_ms', {
  description: 'Bet settlement end-to-end latency in milliseconds',
  unit: 'ms',
  advice: { explicitBucketBoundaries: [10, 50, 100, 500, 1000, 5000, 10000] },
});

export const bettingVolumeUsd = meter.createCounter('yeet_betting_volume_usd_total', {
  description: 'Total USD wagered',
  unit: 'USD',
});

export const betVoidsTotal = meter.createCounter('yeet_bet_voids_total', {
  description: 'Total bet voids by reason',
});

// ─── Wallet metrics ───────────────────────────────────────────────────────────
export const walletTransfersTotal = meter.createCounter('yeet_wallet_transfers_total', {
  description: 'Total wallet transfers by type and status',
});

export const walletIdempotencyHits = meter.createCounter('yeet_wallet_idempotency_hits_total', {
  description: 'Number of idempotency cache hits on wallet writes',
});

export const walletTransferDuration = meter.createHistogram('yeet_wallet_transfer_duration_ms', {
  description: 'Wallet transfer latency in milliseconds',
  unit: 'ms',
  advice: { explicitBucketBoundaries: [5, 10, 25, 50, 100, 200, 500, 1000] },
});

export const walletBalanceReadDuration = meter.createHistogram('yeet_wallet_balance_read_duration_ms', {
  description: 'Wallet balance read latency in milliseconds',
  unit: 'ms',
  advice: { explicitBucketBoundaries: [1, 5, 10, 25, 50, 100] },
});

// ─── Risk metrics ─────────────────────────────────────────────────────────────
export const riskEvaluationsTotal = meter.createCounter('yeet_risk_evaluations_total', {
  description: 'Risk evaluations by decision (allow, review, reject)',
});

export const riskEvalDuration = meter.createHistogram('yeet_risk_eval_duration_ms', {
  description: 'Risk evaluation latency in milliseconds',
  unit: 'ms',
  advice: { explicitBucketBoundaries: [5, 10, 25, 50, 80, 100, 200, 500] },
});

export const riskCircuitBreakerOpen = meter.createCounter('yeet_risk_circuit_breaker_open_total', {
  description: 'Number of times risk service circuit breaker opened',
});

export const riskFlagsTotal = meter.createCounter('yeet_risk_flags_total', {
  description: 'Risk flag detections by flag type',
});

// ─── Session metrics ──────────────────────────────────────────────────────────
export const activeGameSessions = meter.createObservableGauge('yeet_active_game_sessions', {
  description: 'Current number of active game sessions',
});

export const gameSessionCreatedTotal = meter.createCounter('yeet_game_session_created_total', {
  description: 'Total game sessions created by game_id',
});

export const gameSessionEndedTotal = meter.createCounter('yeet_game_session_ended_total', {
  description: 'Total game sessions ended by reason',
});

// ─── Idempotency metrics ──────────────────────────────────────────────────────
export const idempotencyHitsTotal = meter.createCounter('yeet_idempotency_hits_total', {
  description: 'Number of idempotency key cache hits by endpoint',
});

// ─── HTTP metrics ─────────────────────────────────────────────────────────────
// NOTE: Do NOT use these for mesh-level RED metrics — Istio already emits
// istio_requests_total and istio_request_duration_milliseconds.
// These are app-level counters for business routing context (route, synthetic).
export const httpRequestDuration = meter.createHistogram('yeet_http_request_duration_ms', {
  description: 'HTTP request duration by route, method, status — app layer only',
  unit: 'ms',
  advice: { explicitBucketBoundaries: [5, 10, 25, 50, 100, 200, 500, 1000, 2000, 5000] },
});

export const httpRequestsTotal = meter.createCounter('yeet_http_requests_total', {
  description: 'Total HTTP requests by method, route, status, and synthetic flag',
});

// ─── Config metrics ───────────────────────────────────────────────────────────
export const configFlagReadsTotal = meter.createCounter('yeet_config_flag_reads_total', {
  description: 'Total feature flag reads by cache hit/miss',
});

// ─── Observability pipeline self-health ───────────────────────────────────────
export const syntheticChecksTotal = meter.createCounter('yeet_synthetic_checks_total', {
  description: 'Synthetic check executions by check name and result',
});
