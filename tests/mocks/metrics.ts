// Silent stub for all OTEL metrics — prevents SDK initialisation in unit tests.
// Keep in sync with src/telemetry/metrics.ts.
const noop = () => {};
const counter    = { add: noop };
const histogram  = { record: noop };
const gauge      = { addCallback: noop };

// Auth
export const authTokensIssued        = counter;
export const authFailures            = counter;
export const authSessionRevocations  = counter;
export const authRefreshTotal        = counter;

// Bet
export const betPlacementsTotal      = counter;
export const betSettlementsTotal     = counter;
export const betPlacementDuration    = histogram;
export const betSettlementDuration   = histogram;
export const bettingVolumeUsd        = counter;
export const betVoidsTotal           = counter;

// Wallet
export const walletTransfersTotal    = counter;
export const walletIdempotencyHits   = counter;
export const walletTransferDuration  = histogram;
export const walletBalanceReadDuration = histogram;

// Risk
export const riskEvaluationsTotal    = counter;
export const riskEvalDuration        = histogram;
export const riskCircuitBreakerOpen  = counter;
export const riskFlagsTotal          = counter;

// Game sessions
export const activeGameSessions      = gauge;
export const gameSessionCreatedTotal = counter;
export const gameSessionEndedTotal   = counter;

// Idempotency / HTTP / Config / Synthetic
export const idempotencyHitsTotal    = counter;
export const httpRequestDuration     = histogram;
export const httpRequestsTotal       = counter;
export const configFlagReadsTotal    = counter;
export const syntheticChecksTotal    = counter;
