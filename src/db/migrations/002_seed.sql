-- ────────────────────────────────────────────────────────────────────────────
-- Seed data for local development
-- Password for all seed users: "Password123!"
-- bcrypt hash of "Password123!" with 12 rounds
-- ────────────────────────────────────────────────────────────────────────────

-- Seed users
INSERT INTO users (user_id, email, username, password_hash, status, kyc_status, roles)
VALUES
  (
    '00000000-0000-0000-0000-000000000001',
    'player1@yeet.com',
    'player1',
    '$2a$12$xGJnphrg7.n37LSzw6Sdq.rBtVdyGzpJRCZI3r5rSdoAJ0oHhS7o.',
    'active',
    'verified',
    ARRAY['player']
  ),
  (
    '00000000-0000-0000-0000-000000000002',
    'player2@yeet.com',
    'player2',
    '$2a$12$xGJnphrg7.n37LSzw6Sdq.rBtVdyGzpJRCZI3r5rSdoAJ0oHhS7o.',
    'active',
    'verified',
    ARRAY['player']
  ),
  (
    '00000000-0000-0000-0000-000000000099',
    'admin@yeet.com',
    'admin',
    '$2a$12$xGJnphrg7.n37LSzw6Sdq.rBtVdyGzpJRCZI3r5rSdoAJ0oHhS7o.',
    'active',
    'verified',
    ARRAY['player', 'admin']
  )
ON CONFLICT (email) DO NOTHING;

-- Seed wallets
INSERT INTO wallet_accounts (user_id, currency, balance)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'USD', 1000.00),
  ('00000000-0000-0000-0000-000000000002', 'USD', 500.00),
  ('00000000-0000-0000-0000-000000000099', 'USD', 10000.00)
ON CONFLICT (user_id) DO NOTHING;

-- Seed risk profiles
INSERT INTO user_risk_profiles (user_id, risk_score, risk_tier)
VALUES
  ('00000000-0000-0000-0000-000000000001', 10, 'standard'),
  ('00000000-0000-0000-0000-000000000002', 5, 'low'),
  ('00000000-0000-0000-0000-000000000099', 0, 'low')
ON CONFLICT (user_id) DO NOTHING;

-- Seed user limits
INSERT INTO user_limits (user_id, deposit_limit_daily, loss_limit_daily, session_limit_minutes)
VALUES
  ('00000000-0000-0000-0000-000000000001', 5000.00, 1000.00, 240),
  ('00000000-0000-0000-0000-000000000002', 1000.00, 500.00, 120)
ON CONFLICT (user_id) DO NOTHING;

-- Seed feature flags
INSERT INTO feature_flags (flag_key, enabled, rollout_pct, variant)
VALUES
  ('crash_game_enabled',       true,  100, 'v1'),
  ('slots_game_enabled',       true,  100, 'v1'),
  ('fraud_gate_high_value',    true,  100, NULL),
  ('new_wallet_ui',            false,   0, NULL),
  ('risk_eval_enabled',        true,  100, NULL)
ON CONFLICT (flag_key) DO NOTHING;

INSERT INTO schema_migrations (version) VALUES ('002_seed')
  ON CONFLICT (version) DO NOTHING;
