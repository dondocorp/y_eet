import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { ConfigService } from '../../services/ConfigService';
import { requireAuth, requireRole } from '../../middleware/auth';

const UpsertFlagSchema = z.object({
  enabled: z.boolean(),
  rollout_pct: z.number().int().min(0).max(100).optional(),
  variant: z.string().optional(),
});

export async function configRoutes(fastify: FastifyInstance): Promise<void> {
  const configService = new ConfigService();

  // GET /api/v1/config/flags
  fastify.get('/flags', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const flags = await configService.getFlags();
    return reply.code(200).send({
      flags,
      fetched_at: new Date(),
    });
  });

  // GET /api/v1/config/flags/:flagKey
  fastify.get('/flags/:flagKey', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const { flagKey } = request.params as { flagKey: string };
    const flag = await configService.getFlag(flagKey);
    if (!flag) return reply.code(404).send({ code: 'FLAG_NOT_FOUND', flag_key: flagKey });
    return reply.code(200).send(flag);
  });

  // PUT /api/v1/config/flags/:flagKey — admin only
  fastify.put('/flags/:flagKey', {
    preHandler: [requireAuth, requireRole('admin')],
  }, async (request, reply) => {
    const { flagKey } = request.params as { flagKey: string };
    const body = UpsertFlagSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const flag = await configService.upsertFlag({
      flagKey,
      enabled: body.data.enabled,
      rolloutPct: body.data.rollout_pct,
      variant: body.data.variant,
    });

    return reply.code(200).send(flag);
  });
}
