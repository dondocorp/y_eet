import { User, WalletAccount, WalletTransaction, Bet, GameSession, UserRiskProfile, FeatureFlag } from '../src/types';

export const makeUser = (overrides: Partial<User> = {}): User => ({
  userId:       '00000000-0000-0000-0000-000000000001',
  email:        'player1@yeet.com',
  username:     'player1',
  passwordHash: '$2a$01$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', // bcrypt rounds=1
  status:       'active',
  kycStatus:    'verified',
  jurisdiction: 'MT',
  roles:        ['player'],
  createdAt:    new Date('2025-01-01'),
  updatedAt:    new Date('2025-01-01'),
  ...overrides,
});

export const makeAdminUser = (overrides: Partial<User> = {}): User =>
  makeUser({ userId: '00000000-0000-0000-0000-000000000099', email: 'admin@yeet.com', username: 'admin', roles: ['player', 'admin'], ...overrides });

export const makeWallet = (overrides: Partial<WalletAccount> = {}): WalletAccount => ({
  walletId:  'wallet-0001',
  userId:    '00000000-0000-0000-0000-000000000001',
  currency:  'USD',
  balance:   '1000.00',
  reserved:  '0.00',
  createdAt: new Date('2025-01-01'),
  updatedAt: new Date('2025-01-01'),
  ...overrides,
});

export const makeWalletTx = (overrides: Partial<WalletTransaction> = {}): WalletTransaction => ({
  txId:           'tx-0001',
  walletId:       'wallet-0001',
  userId:         '00000000-0000-0000-0000-000000000001',
  type:           'bet_reserve',
  amount:         '-50.00',
  balanceAfter:   '950.00',
  referenceId:    'bet-0001',
  idempotencyKey: 'idem-0001',
  createdAt:      new Date('2025-01-01'),
  ...overrides,
});

export const makeBet = (overrides: Partial<Bet> = {}): Bet => ({
  betId:          'bet-0001',
  userId:         '00000000-0000-0000-0000-000000000001',
  gameId:         'game_crash_v1',
  idempotencyKey: 'idem-0001',
  status:         'accepted',
  amount:         '50.00',
  currency:       'USD',
  betType:        'crash',
  parameters:     { auto_cashout: 2.0 },
  placedAt:       new Date('2025-01-01'),
  ...overrides,
});

export const makeGameSession = (overrides: Partial<GameSession> = {}): GameSession => ({
  sessionId:        'gsess-0001',
  userId:           '00000000-0000-0000-0000-000000000001',
  gameId:           'game_crash_v1',
  status:           'active',
  clientSeed:       'client-seed-123',
  serverSeed:       'server-seed-abc',
  serverSeedHash:   'sha256-hash-of-server-seed',
  startedAt:        new Date('2025-01-01'),
  lastHeartbeatAt:  new Date(),
  expiresAt:        new Date(Date.now() + 30 * 60 * 1000),
  ...overrides,
});

export const makeRiskProfile = (overrides: Partial<UserRiskProfile> = {}): UserRiskProfile => ({
  userId:          '00000000-0000-0000-0000-000000000001',
  riskScore:       10,
  riskTier:        'standard',
  flags:           [],
  lastEvaluatedAt: new Date(),
  updatedAt:       new Date(),
  ...overrides,
});

export const makeFeatureFlag = (overrides: Partial<FeatureFlag> = {}): FeatureFlag => ({
  flagKey:    'test_flag',
  enabled:    true,
  rolloutPct: 100,
  createdAt:  new Date(),
  updatedAt:  new Date(),
  ...overrides,
});
