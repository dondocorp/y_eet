-- ────────────────────────────────────────────────────────────────────────────
-- Yeet Platform — Initial Schema
-- ────────────────────────────────────────────────────────────────────────────

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ─── Users ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  user_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email             TEXT UNIQUE NOT NULL,
  username          TEXT UNIQUE NOT NULL,
  password_hash     TEXT NOT NULL,
  status            TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'suspended', 'self_excluded')),
  kyc_status        TEXT NOT NULL DEFAULT 'pending'
                      CHECK (kyc_status IN ('pending', 'submitted', 'verified', 'rejected')),
  jurisdiction      TEXT NOT NULL DEFAULT 'MT',
  roles             TEXT[] NOT NULL DEFAULT ARRAY['player'],
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);

-- ─── Sessions (refresh tokens) ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
  session_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  refresh_token_hash  TEXT NOT NULL,
  device_fingerprint  TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at          TIMESTAMPTZ NOT NULL,
  used_at             TIMESTAMPTZ,
  revoked_at          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);

-- ─── Wallet accounts ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS wallet_accounts (
  wallet_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID UNIQUE NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  currency    TEXT NOT NULL DEFAULT 'USD',
  balance     NUMERIC(15, 2) NOT NULL DEFAULT 0.00 CHECK (balance >= 0),
  reserved    NUMERIC(15, 2) NOT NULL DEFAULT 0.00 CHECK (reserved >= 0),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Wallet transactions (immutable ledger) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS wallet_transactions (
  tx_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  wallet_id         UUID NOT NULL REFERENCES wallet_accounts(wallet_id),
  user_id           UUID NOT NULL REFERENCES users(user_id),
  type              TEXT NOT NULL
                      CHECK (type IN ('deposit','withdrawal','bet_reserve','bet_release','bet_win','adjustment')),
  amount            NUMERIC(15, 2) NOT NULL,
  balance_after     NUMERIC(15, 2) NOT NULL,
  reference_id      TEXT,
  idempotency_key   TEXT UNIQUE NOT NULL,
  metadata          JSONB,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wallet_tx_user ON wallet_transactions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_reference ON wallet_transactions(reference_id);
CREATE INDEX IF NOT EXISTS idx_wallet_tx_idem ON wallet_transactions(idempotency_key);

-- ─── Idempotency keys (cross-endpoint deduplication) ─────────────────────────
CREATE TABLE IF NOT EXISTS idempotency_keys (
  key           TEXT NOT NULL,
  service       TEXT NOT NULL,
  endpoint      TEXT NOT NULL,
  status_code   INT NOT NULL,
  response_body JSONB NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at    TIMESTAMPTZ NOT NULL,
  PRIMARY KEY (key, service)
);

CREATE INDEX IF NOT EXISTS idx_idem_expires ON idempotency_keys(expires_at);

-- ─── Game sessions ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS game_sessions (
  session_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             UUID NOT NULL REFERENCES users(user_id),
  game_id             TEXT NOT NULL,
  status              TEXT NOT NULL DEFAULT 'active'
                        CHECK (status IN ('active', 'closed', 'expired')),
  client_seed         TEXT,
  server_seed         TEXT,
  server_seed_hash    TEXT NOT NULL,
  idempotency_key     TEXT UNIQUE,
  started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  last_heartbeat_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at           TIMESTAMPTZ,
  expires_at          TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '30 minutes')
);

CREATE INDEX IF NOT EXISTS idx_game_sessions_user ON game_sessions(user_id, status);
CREATE INDEX IF NOT EXISTS idx_game_sessions_expires ON game_sessions(expires_at) WHERE status = 'active';

-- ─── Bets ─────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bets (
  bet_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES users(user_id),
  session_id        UUID REFERENCES game_sessions(session_id),
  game_id           TEXT NOT NULL,
  idempotency_key   TEXT UNIQUE NOT NULL,
  status            TEXT NOT NULL DEFAULT 'accepted'
                      CHECK (status IN ('accepted','pending_settlement','settled','voided')),
  amount            NUMERIC(15, 2) NOT NULL CHECK (amount > 0),
  currency          TEXT NOT NULL DEFAULT 'USD',
  payout            NUMERIC(15, 2),
  bet_type          TEXT NOT NULL,
  parameters        JSONB,
  risk_score        INT,
  risk_decision     TEXT,
  wallet_tx_id      UUID REFERENCES wallet_transactions(tx_id),
  placed_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  settled_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bets_user ON bets(user_id, placed_at DESC);
CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);
CREATE INDEX IF NOT EXISTS idx_bets_session ON bets(session_id);
CREATE INDEX IF NOT EXISTS idx_bets_idem ON bets(idempotency_key);

-- ─── Fraud signals ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS fraud_signals (
  signal_id   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(user_id),
  signal_type TEXT NOT NULL,
  severity    TEXT NOT NULL CHECK (severity IN ('low','medium','high','critical')),
  context     JSONB,
  occurred_at TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fraud_signals_user ON fraud_signals(user_id, created_at DESC);

-- ─── User risk profiles ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_risk_profiles (
  user_id             UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
  risk_score          INT NOT NULL DEFAULT 0 CHECK (risk_score >= 0 AND risk_score <= 100),
  risk_tier           TEXT NOT NULL DEFAULT 'standard'
                        CHECK (risk_tier IN ('low','standard','elevated','high','blocked')),
  flags               TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  last_evaluated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Feature flags ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_flags (
  flag_key    TEXT PRIMARY KEY,
  enabled     BOOLEAN NOT NULL DEFAULT false,
  rollout_pct INT NOT NULL DEFAULT 0 CHECK (rollout_pct >= 0 AND rollout_pct <= 100),
  variant     TEXT,
  metadata    JSONB,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── User limits (responsible gaming) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_limits (
  user_id               UUID PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
  deposit_limit_daily   NUMERIC(15, 2),
  deposit_limit_weekly  NUMERIC(15, 2),
  loss_limit_daily      NUMERIC(15, 2),
  session_limit_minutes INT,
  self_exclusion_until  TIMESTAMPTZ,
  cooling_off_until     TIMESTAMPTZ,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── Migration tracking ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS schema_migrations (
  version     TEXT PRIMARY KEY,
  applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO schema_migrations (version) VALUES ('001_initial')
  ON CONFLICT (version) DO NOTHING;
