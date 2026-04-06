import { metrics } from '@opentelemetry/api';

const meter = metrics.getMeter('yeet-platform-api');

// ─── Auth metrics ─────────────────────────────────────────────────────────────
export const authTokensIssued = meter.createCounter('yeet_auth_tokens_issued_total', {
  description: 'Total number of JWT tokens issued',
});

export const authFailures = meter.createCounter('yeet_auth_failures_total', {
  description: 'Auth failures by reason',
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
});

export const bettingVolumeUsd = meter.createCounter('yeet_betting_volume_usd_total', {
  description: 'Total USD wagered',
  unit: 'USD',
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
});

// ─── Risk metrics ─────────────────────────────────────────────────────────────
export const riskEvaluationsTotal = meter.createCounter('yeet_risk_evaluations_total', {
  description: 'Risk evaluations by decision',
});

export const riskEvalDuration = meter.createHistogram('yeet_risk_eval_duration_ms', {
  description: 'Risk evaluation latency in milliseconds',
  unit: 'ms',
});

export const riskCircuitBreakerOpen = meter.createCounter('yeet_risk_circuit_breaker_open_total', {
  description: 'Number of times risk service circuit breaker opened',
});

// ─── Session metrics ──────────────────────────────────────────────────────────
export const activeGameSessions = meter.createObservableGauge('yeet_active_game_sessions', {
  description: 'Current number of active game sessions',
});

// ─── Idempotency metrics ──────────────────────────────────────────────────────
export const idempotencyHitsTotal = meter.createCounter('yeet_idempotency_hits_total', {
  description: 'Number of idempotency key cache hits by endpoint',
});

// ─── HTTP metrics ─────────────────────────────────────────────────────────────
export const httpRequestDuration = meter.createHistogram('yeet_http_request_duration_ms', {
  description: 'HTTP request duration in milliseconds',
  unit: 'ms',
});

export const httpRequestsTotal = meter.createCounter('yeet_http_requests_total', {
  description: 'Total HTTP requests by method, route, and status',
});
