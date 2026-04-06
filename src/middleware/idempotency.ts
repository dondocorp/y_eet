import { FastifyRequest, FastifyReply } from 'fastify';
import { IdempotencyRepository } from '../repositories/IdempotencyRepository';
import { idempotencyHitsTotal } from '../telemetry/metrics';

const repo = new IdempotencyRepository();

export interface IdempotencyMeta {
  key: string;
  service: string;
  endpoint: string;
  ttlHours: number;
}

// Symbol used to attach idempotency metadata to the request
export const IDEMPOTENCY_META = Symbol('idempotencyMeta');

/**
 * Fastify preHandler factory — checks idempotency keys for mutating endpoints.
 *
 * Flow:
 *   1. Idempotency-Key header missing → 400
 *   2. Key found in store → return cached response immediately
 *   3. Key is new → set metadata on request so the app onSend hook can persist the response
 */
export function idempotencyGuard(service: string, endpoint: string, ttlHours = 24) {
  return async (request: FastifyRequest, reply: FastifyReply): Promise<void> => {
    const key = request.headers['idempotency-key'] as string | undefined;

    if (!key) {
      return reply.code(400).send({
        code: 'MISSING_IDEMPOTENCY_KEY',
        message: 'Idempotency-Key header is required for this endpoint',
        request_id: request.requestId,
      });
    }

    request.idempotencyKey = key;

    const existing = await repo.get(key, service);
    if (existing) {
      idempotencyHitsTotal.add(1, { service, endpoint });
      reply.header('X-Idempotency-Replay', 'true');
      return reply.code(existing.statusCode).send(existing.responseBody);
    }

    // Attach metadata for the onSend hook in app.ts
    (request as unknown as Record<symbol, IdempotencyMeta>)[IDEMPOTENCY_META] = {
      key,
      service,
      endpoint,
      ttlHours,
    };
  };
}

/**
 * Called from app.ts onSend hook to persist idempotency response.
 */
export async function persistIdempotencyResponse(
  request: FastifyRequest,
  statusCode: number,
  payload: unknown,
): Promise<void> {
  const meta = (request as unknown as Record<symbol, IdempotencyMeta | undefined>)[IDEMPOTENCY_META];
  if (!meta) return;

  // Only cache successful or known-idempotent responses
  if (statusCode >= 200 && statusCode < 500) {
    let body: unknown;
    try {
      body = typeof payload === 'string' ? JSON.parse(payload) : payload;
    } catch {
      body = payload;
    }
    await repo.set(meta.key, meta.service, meta.endpoint, statusCode, body, meta.ttlHours).catch(() => {
      // Non-fatal — idempotency store failure must not fail the request
    });
  }
}
