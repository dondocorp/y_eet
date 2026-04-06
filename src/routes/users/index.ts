import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { UserRepository } from '../../repositories/UserRepository';
import { requireAuth, requireSelfOrAdmin } from '../../middleware/auth';
import { UserNotFoundError } from '../../errors';

const UpdateProfileSchema = z.object({
  username: z.string().min(3).max(30).regex(/^[a-zA-Z0-9_]+$/).optional(),
}).strict();

export async function userRoutes(fastify: FastifyInstance): Promise<void> {
  const userRepo = new UserRepository();

  // GET /api/v1/users/:userId/profile
  fastify.get('/:userId/profile', {
    preHandler: [requireAuth, requireSelfOrAdmin],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const user = await userRepo.findById(userId);
    if (!user) throw new UserNotFoundError(userId);

    return reply.code(200).send({
      user_id: user.userId,
      email: user.email,
      username: user.username,
      status: user.status,
      kyc_status: user.kycStatus,
      jurisdiction: user.jurisdiction,
      roles: user.roles,
      created_at: user.createdAt,
    });
  });

  // PATCH /api/v1/users/:userId/profile
  fastify.patch('/:userId/profile', {
    preHandler: [requireAuth, requireSelfOrAdmin],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const body = UpdateProfileSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const user = await userRepo.findById(userId);
    if (!user) throw new UserNotFoundError(userId);

    // In a real system, execute the update; for now, return current profile
    return reply.code(200).send({
      user_id: user.userId,
      email: user.email,
      username: body.data.username ?? user.username,
      status: user.status,
      kyc_status: user.kycStatus,
    });
  });

  // GET /api/v1/users/:userId/limits
  fastify.get('/:userId/limits', {
    preHandler: [requireAuth, requireSelfOrAdmin],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const limits = await userRepo.getLimits(userId);
    return reply.code(200).send({
      user_id: userId,
      deposit_limit_daily: limits?.depositLimitDaily ?? null,
      deposit_limit_weekly: limits?.depositLimitWeekly ?? null,
      loss_limit_daily: limits?.lossLimitDaily ?? null,
      session_limit_minutes: limits?.sessionLimitMinutes ?? null,
      self_exclusion_until: limits?.selfExclusionUntil ?? null,
      cooling_off_until: limits?.coolingOffUntil ?? null,
    });
  });
}
