/**
 * OTEL must be initialized before anything else.
 * The SDK patches Node.js modules at require-time.
 */
import './telemetry/tracer';

import { buildApp } from './app';
import { config } from './config';
import { runMigrations } from './db/migrate';
import { pool } from './db/pool';

async function main(): Promise<void> {
  // Run DB migrations before accepting traffic
  console.log('Running database migrations...');
  await runMigrations();
  console.log('Migrations complete');

  const app = await buildApp();

  await app.listen({ port: config.PORT, host: '0.0.0.0' });
  console.log(`${config.SERVICE_NAME} v${config.SERVICE_VERSION} listening on port ${config.PORT}`);
  console.log(`Prometheus metrics on port ${config.PROMETHEUS_PORT}/metrics`);
}

// Graceful shutdown
const shutdown = async (signal: string): Promise<void> => {
  console.log(`Received ${signal} — shutting down gracefully`);
  await pool.end();
  process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

process.on('unhandledRejection', (reason) => {
  console.error('Unhandled rejection:', reason);
  process.exit(1);
});

main().catch((err) => {
  console.error('Fatal startup error:', err);
  process.exit(1);
});
