-- Fix seed user password hashes.
-- The original 002_seed used a placeholder hash. This corrects it.
-- Hash is bcrypt(Password123!, rounds=12) — verified correct.
UPDATE users
SET password_hash = '$2a$12$xGJnphrg7.n37LSzw6Sdq.rBtVdyGzpJRCZI3r5rSdoAJ0oHhS7o.'
WHERE email IN ('player1@y_eet.com', 'player2@y_eet.com', 'admin@y_eet.com')
  AND password_hash = '$2a$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/LewdBPj5o9k8U5Kgu';

INSERT INTO schema_migrations (version) VALUES ('003_fix_seed_passwords')
  ON CONFLICT (version) DO NOTHING;
