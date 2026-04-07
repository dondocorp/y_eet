import { FastifyInstance } from 'fastify';
import { requireAuth, requireRole } from '../../middleware/auth';
import { pool, checkConnection } from '../../db/pool';
import { config } from '../../config';

export async function adminRoutes(fastify: FastifyInstance): Promise<void> {
  // GET /_internal/status
  fastify.get('/status', {
    preHandler: [requireAuth, requireRole('admin')],
  }, async (_request, reply) => {
    const dbOk = await checkConnection();
    return reply.code(200).send({
      service: config.SERVICE_NAME,
      version: config.SERVICE_VERSION,
      env: config.NODE_ENV,
      uptime_seconds: Math.floor(process.uptime()),
      db_healthy: dbOk,
      db_pool: {
        total: pool.totalCount,
        idle: pool.idleCount,
        waiting: pool.waitingCount,
      },
      memory_mb: Math.round(process.memoryUsage().heapUsed / 1024 / 1024),
      timestamp: new Date(),
    });
  });

  // GET /_internal/config — runtime config (redacted)
  fastify.get('/config', {
    preHandler: [requireAuth, requireRole('admin')],
  }, async (_request, reply) => {
    return reply.code(200).send({
      service_name: config.SERVICE_NAME,
      service_version: config.SERVICE_VERSION,
      node_env: config.NODE_ENV,
      port: config.PORT,
      jwt_expiry: config.JWT_EXPIRY,
      risk_eval_timeout_ms: config.RISK_EVAL_TIMEOUT_MS,
      rate_limit_max: config.RATE_LIMIT_MAX,
      log_level: config.LOG_LEVEL,
      // Secrets are never returned
    });
  });

  // GET /_internal/db/stats
  fastify.get('/db/stats', {
    preHandler: [requireAuth, requireRole('admin')],
  }, async (_request, reply) => {
    const result = await pool.query<Record<string, unknown>>(`
      SELECT
        schemaname,
        relname as table_name,
        n_live_tup as live_rows,
        n_dead_tup as dead_rows,
        last_autovacuum,
        last_autoanalyze
      FROM pg_stat_user_tables
      ORDER BY n_live_tup DESC
    `);
    return reply.code(200).send({ tables: result.rows });
  });
}
