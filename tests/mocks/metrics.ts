// Silent stub for all OTEL metrics — prevents SDK initialisation in unit tests.
const noop = () => {};
const counter    = { add: noop };
const histogram  = { record: noop };
const gauge      = { addCallback: noop };
const observable = { observe: noop };

export const authTokensIssued      = counter;
export const authFailures          = counter;
export const betPlacementsTotal    = counter;
export const betSettlementsTotal   = counter;
export const betPlacementDuration  = histogram;
export const bettingVolumeUsd      = counter;
export const walletTransfersTotal  = counter;
export const walletIdempotencyHits = counter;
export const walletTransferDuration = histogram;
export const riskEvaluationsTotal  = counter;
export const riskEvalDuration      = histogram;
export const riskCircuitBreakerOpen = counter;
export const activeGameSessions    = gauge;
export const idempotencyHitsTotal  = counter;
export const httpRequestDuration   = histogram;
export const httpRequestsTotal     = counter;
