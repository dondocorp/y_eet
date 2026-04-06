export class AppError extends Error {
  constructor(
    public readonly code: string,
    message: string,
    public readonly statusCode: number,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
    this.name = 'AppError';
  }
}

export class InsufficientFundsError extends AppError {
  constructor(available: string, required: string) {
    super('INSUFFICIENT_FUNDS', 'Insufficient wallet balance', 402, { available, required });
  }
}

export class IdempotencyConflictError extends AppError {
  constructor(key: string) {
    super('IDEMPOTENCY_CONFLICT', 'Idempotency key reused with different payload', 409, { key });
  }
}

export class DuplicateOperationError extends AppError {
  constructor(existingId: string) {
    super('DUPLICATE_OPERATION', 'Duplicate request — returning existing result', 409, { existingId });
  }
}

export class UserNotFoundError extends AppError {
  constructor(userId: string) {
    super('USER_NOT_FOUND', 'User not found', 404, { userId });
  }
}

export class SessionNotFoundError extends AppError {
  constructor(sessionId: string) {
    super('SESSION_NOT_FOUND', 'Game session not found', 404, { sessionId });
  }
}

export class SessionExpiredError extends AppError {
  constructor(sessionId: string) {
    super('SESSION_EXPIRED', 'Game session has expired', 422, { sessionId });
  }
}

export class BetNotFoundError extends AppError {
  constructor(betId: string) {
    super('BET_NOT_FOUND', 'Bet not found', 404, { betId });
  }
}

export class BetAlreadySettledError extends AppError {
  constructor(betId: string) {
    super('BET_ALREADY_SETTLED', 'Bet has already been settled', 409, { betId });
  }
}

export class UserSuspendedError extends AppError {
  constructor() {
    super('ACCOUNT_SUSPENDED', 'Account is suspended', 403);
  }
}

export class KycRequiredError extends AppError {
  constructor() {
    super('KYC_REQUIRED', 'KYC verification required to place bets', 403);
  }
}

export class RiskRejectedError extends AppError {
  constructor(reason: string) {
    super('RISK_REJECTED', 'Bet rejected by risk evaluation', 403, { reason });
  }
}

export class RiskServiceUnavailableError extends AppError {
  constructor() {
    super('RISK_SERVICE_UNAVAILABLE', 'Risk evaluation service unavailable', 503);
  }
}

export class BetLimitExceededError extends AppError {
  constructor(limit: string, type: string) {
    super('BET_LIMIT_EXCEEDED', `${type} limit exceeded`, 422, { limit, type });
  }
}

export class WalletNotFoundError extends AppError {
  constructor(userId: string) {
    super('WALLET_NOT_FOUND', 'Wallet not found', 404, { userId });
  }
}

export class UnauthorizedError extends AppError {
  constructor(message = 'Unauthorized') {
    super('UNAUTHORIZED', message, 401);
  }
}

export class ForbiddenError extends AppError {
  constructor(message = 'Forbidden') {
    super('FORBIDDEN', message, 403);
  }
}
