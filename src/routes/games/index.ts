import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { GameSessionService } from '../../services/GameSessionService';
import { requireAuth } from '../../middleware/auth';

const CreateSessionSchema = z.object({
  game_id: z.string().min(1),
  client_seed: z.string().optional(),
});

export async function gameRoutes(fastify: FastifyInstance): Promise<void> {
  const gameSessionService = new GameSessionService();

  // POST /api/v1/games/sessions
  fastify.post('/sessions', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const body = CreateSessionSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const idempotencyKey = request.headers['idempotency-key'] as string | undefined;

    const session = await gameSessionService.createSession({
      userId: request.actor!.userId,
      gameId: body.data.game_id,
      clientSeed: body.data.client_seed,
      idempotencyKey,
    });

    return reply.code(201).send({
      session_id: session.sessionId,
      game_id: session.gameId,
      status: session.status,
      server_seed_hash: session.serverSeedHash,
      started_at: session.startedAt,
      expires_at: session.expiresAt,
    });
  });

  // GET /api/v1/games/sessions/:sessionId
  fastify.get('/sessions/:sessionId', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const { sessionId } = request.params as { sessionId: string };
    const session = await gameSessionService.getSession(sessionId, request.actor!.userId);

    return reply.code(200).send({
      session_id: session.sessionId,
      game_id: session.gameId,
      status: session.status,
      server_seed_hash: session.serverSeedHash,
      started_at: session.startedAt,
      last_heartbeat_at: session.lastHeartbeatAt,
      closed_at: session.closedAt,
      expires_at: session.expiresAt,
    });
  });

  // POST /api/v1/games/sessions/:sessionId/heartbeat
  fastify.post('/sessions/:sessionId/heartbeat', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const { sessionId } = request.params as { sessionId: string };
    const session = await gameSessionService.heartbeat(sessionId, request.actor!.userId);
    return reply.code(200).send({
      session_id: session.sessionId,
      expires_at: session.expiresAt,
    });
  });

  // POST /api/v1/games/sessions/:sessionId/close
  fastify.post('/sessions/:sessionId/close', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const { sessionId } = request.params as { sessionId: string };
    const session = await gameSessionService.closeSession(sessionId, request.actor!.userId);
    return reply.code(200).send({ session_id: session.sessionId, status: session.status });
  });

  // GET /api/v1/games/sessions/:sessionId/seed-reveal
  fastify.get('/sessions/:sessionId/seed-reveal', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const { sessionId } = request.params as { sessionId: string };
    const seeds = await gameSessionService.revealServerSeed(sessionId, request.actor!.userId);
    return reply.code(200).send(seeds);
  });
}
