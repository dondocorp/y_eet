import { z } from 'zod';

const ConfigSchema = z.object({
  NODE_ENV: z.enum(['development', 'test', 'production']).default('development'),
  PORT: z.coerce.number().default(8080),
  SERVICE_NAME: z.string().default('y_eet-platform-api'),
  SERVICE_VERSION: z.string().default('1.0.0'),

  DATABASE_URL: z.string().default('postgres://y_eet:y_eet@localhost:5432/y_eet'),

  JWT_SECRET: z.string().min(32).default('local-dev-secret-min-32-chars-here!!'),
  JWT_EXPIRY: z.string().default('15m'),
  REFRESH_TOKEN_EXPIRY_DAYS: z.coerce.number().default(7),
  BCRYPT_ROUNDS: z.coerce.number().default(12),

  RATE_LIMIT_MAX: z.coerce.number().default(100),
  RATE_LIMIT_WINDOW_MS: z.coerce.number().default(60000),

  RISK_EVAL_TIMEOUT_MS: z.coerce.number().default(80),

  LOG_LEVEL: z.enum(['trace', 'debug', 'info', 'warn', 'error', 'silent']).default('info'),
  OTEL_EXPORTER_OTLP_ENDPOINT: z.string().default('http://localhost:4317'),
  PROMETHEUS_PORT: z.coerce.number().default(9464),

  REDIS_URL: z.string().optional(),
});

const parsed = ConfigSchema.safeParse(process.env);

if (!parsed.success) {
  console.error('Invalid configuration:');
  console.error(parsed.error.flatten().fieldErrors);
  process.exit(1);
}

export const config = parsed.data;
export type Config = typeof config;
