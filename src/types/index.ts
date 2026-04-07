// ─── Domain Types ────────────────────────────────────────────────────────────

export type UserStatus = 'active' | 'suspended' | 'self_excluded';
export type KycStatus = 'pending' | 'submitted' | 'verified' | 'rejected';
export type RiskTier = 'low' | 'standard' | 'elevated' | 'high' | 'blocked';
export type BetStatus = 'accepted' | 'pending_settlement' | 'settled' | 'voided';
export type SessionStatus = 'active' | 'closed' | 'expired';
export type TxType = 'deposit' | 'withdrawal' | 'bet_reserve' | 'bet_release' | 'bet_win' | 'adjustment';

export interface User {
  userId: string;
  email: string;
  username: string;
  passwordHash: string;
  status: UserStatus;
  kycStatus: KycStatus;
  jurisdiction: string;
  roles: string[];
  createdAt: Date;
  updatedAt: Date;
}

export interface Session {
  sessionId: string;
  userId: string;
  refreshTokenHash: string;
  deviceFingerprint?: string;
  createdAt: Date;
  expiresAt: Date;
  usedAt?: Date;
  revokedAt?: Date;
}

export interface WalletAccount {
  walletId: string;
  userId: string;
  currency: string;
  balance: string; // NUMERIC — always kept as string to avoid float imprecision
  reserved: string;
  createdAt: Date;
  updatedAt: Date;
}

export interface WalletTransaction {
  txId: string;
  walletId: string;
  userId: string;
  type: TxType;
  amount: string;
  balanceAfter: string;
  referenceId?: string;
  idempotencyKey: string;
  metadata?: Record<string, unknown>;
  createdAt: Date;
}

export interface Bet {
  betId: string;
  userId: string;
  sessionId?: string;
  gameId: string;
  idempotencyKey: string;
  status: BetStatus;
  amount: string;
  currency: string;
  payout?: string;
  betType: string;
  parameters?: Record<string, unknown>;
  riskScore?: number;
  riskDecision?: string;
  walletTxId?: string;
  placedAt: Date;
  settledAt?: Date;
}

export interface GameSession {
  sessionId: string;
  userId: string;
  gameId: string;
  status: SessionStatus;
  clientSeed?: string;
  serverSeed?: string;
  serverSeedHash: string;
  startedAt: Date;
  lastHeartbeatAt: Date;
  closedAt?: Date;
  expiresAt: Date;
}

export interface FraudSignal {
  signalId: string;
  userId: string;
  signalType: string;
  severity: 'low' | 'medium' | 'high' | 'critical';
  context?: Record<string, unknown>;
  occurredAt: Date;
  createdAt: Date;
}

export interface UserRiskProfile {
  userId: string;
  riskScore: number;
  riskTier: RiskTier;
  flags: string[];
  lastEvaluatedAt: Date;
  updatedAt: Date;
}

export interface FeatureFlag {
  flagKey: string;
  enabled: boolean;
  rolloutPct: number;
  variant?: string;
  metadata?: Record<string, unknown>;
  createdAt: Date;
  updatedAt: Date;
}

export interface UserLimits {
  userId: string;
  depositLimitDaily?: string;
  depositLimitWeekly?: string;
  lossLimitDaily?: string;
  sessionLimitMinutes?: number;
  selfExclusionUntil?: Date;
  coolingOffUntil?: Date;
}

export interface IdempotencyRecord {
  key: string;
  service: string;
  endpoint: string;
  statusCode: number;
  responseBody: unknown;
  createdAt: Date;
  expiresAt: Date;
}

// ─── Risk Types ───────────────────────────────────────────────────────────────

export interface RiskEvaluationRequest {
  userId: string;
  action: 'bet_place' | 'login' | 'withdrawal';
  amount?: string;
  sessionId?: string;
  deviceFingerprint?: string;
  ipAddress?: string;
}

export interface RiskEvaluationResult {
  decision: 'allow' | 'reject' | 'review';
  riskScore: number;
  riskTier: RiskTier;
  flags: string[];
  evalId: string;
}

// ─── Fastify augmentation ─────────────────────────────────────────────────────

declare module 'fastify' {
  interface FastifyRequest {
    actor?: {
      userId: string;
      sessionId: string;
      roles: string[];
    };
    requestId: string;
    isSynthetic: boolean;
    idempotencyKey?: string;
  }
}
