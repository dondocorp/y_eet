import { FastifyInstance } from 'fastify';
import { v4 as uuidv4 } from 'uuid';
import { httpRequestsTotal, httpRequestDuration } from '../telemetry/metrics';

/**
 * Registers request ID propagation and HTTP metrics hooks on the root instance.
 * Must be called before route registration.
 */
export function registerRequestMiddleware(fastify: FastifyInstance): void {
  fastify.addHook('onRequest', async (request) => {
    request.requestId =
      (request.headers['x-request-id'] as string) ||
      (request.headers['x-correlation-id'] as string) ||
      uuidv4();

    request.isSynthetic = request.headers['x-synthetic'] === 'true';
  });

  fastify.addHook('onSend', async (_request, reply, payload) => {
    reply.header('X-Service-Version', process.env.SERVICE_VERSION ?? '1.0.0');
    return payload;
  });

  fastify.addHook('onResponse', async (request, reply) => {
    const route = (request.routeOptions as { url?: string } | undefined)?.url ?? request.url;
    const labels = {
      method: request.method,
      route,
      status: String(reply.statusCode),
      synthetic: String(request.isSynthetic),
    };
    httpRequestsTotal.add(1, labels);
    httpRequestDuration.record(reply.elapsedTime, labels);
  });

  fastify.addHook('onSend', async (request, reply, payload) => {
    reply.header('X-Request-ID', request.requestId);
    return payload;
  });
}
