import { FastifyInstance } from 'fastify';
import { checkConnection } from '../../db/pool';
import { config } from '../../config';

export async function healthRoutes(fastify: FastifyInstance): Promise<void> {
  // GET /health/live — liveness: is the process alive?
  fastify.get('/live', async (_request, reply) => {
    return reply.code(200).send({
      status: 'ok',
      service: config.SERVICE_NAME,
      version: config.SERVICE_VERSION,
      uptime_seconds: Math.floor(process.uptime()),
    });
  });

  // GET /health/ready — readiness: can the service take traffic?
  fastify.get('/ready', async (_request, reply) => {
    const dbOk = await checkConnection();
    const allOk = dbOk;

    return reply.code(allOk ? 200 : 503).send({
      status: allOk ? 'ready' : 'not_ready',
      checks: {
        postgres: { status: dbOk ? 'ok' : 'error' },
      },
    });
  });

  // GET /health/startup — one-time startup check
  fastify.get('/startup', async (_request, reply) => {
    const dbOk = await checkConnection();
    return reply.code(dbOk ? 200 : 503).send({ status: dbOk ? 'ready' : 'not_ready' });
  });

  // GET /health/dependencies — detailed dependency status (internal use)
  fastify.get('/dependencies', async (_request, reply) => {
    const start = Date.now();
    const dbOk = await checkConnection();
    const dbLatency = Date.now() - start;

    return reply.code(200).send({
      service: config.SERVICE_NAME,
      version: config.SERVICE_VERSION,
      checks: {
        postgres: { status: dbOk ? 'ok' : 'error', latency_ms: dbLatency },
      },
      checked_at: new Date(),
    });
  });
}
