// Set all required env vars before any module is imported.
// config.ts calls process.exit(1) on invalid config, so this must run first.
process.env.NODE_ENV = 'test';
process.env.PORT = '8080';
process.env.SERVICE_NAME = 'y_eet-test';
process.env.SERVICE_VERSION = '0.0.0';
process.env.DATABASE_URL = 'postgres://test:test@localhost:5432/test';
process.env.JWT_SECRET = 'test-secret-that-is-at-least-32-chars-long!!';
process.env.JWT_EXPIRY = '15m';
process.env.REFRESH_TOKEN_EXPIRY_DAYS = '7';
process.env.BCRYPT_ROUNDS = '1'; // intentionally low — fast hashing in tests
process.env.RATE_LIMIT_MAX = '100';
process.env.RATE_LIMIT_WINDOW_MS = '60000';
process.env.RISK_EVAL_TIMEOUT_MS = '500';
process.env.LOG_LEVEL = 'silent';
process.env.OTEL_EXPORTER_OTLP_ENDPOINT = 'http://localhost:4317';
process.env.PROMETHEUS_PORT = '9465';
