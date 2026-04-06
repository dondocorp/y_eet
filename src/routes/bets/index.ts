import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { BetService } from '../../services/BetService';
import { requireAuth, requireRole } from '../../middleware/auth';
import { idempotencyGuard } from '../../middleware/idempotency';

const PlaceBetSchema = z.object({
  game_session_id: z.string().uuid().optional(),
  game_id: z.string().min(1),
  amount: z.string().regex(/^\d+\.\d{2}$/),
  currency: z.enum(['USD', 'EUR']).default('USD'),
  bet_type: z.string().min(1),
  parameters: z.record(z.unknown()).optional(),
});

const SettleBetSchema = z.object({
  payout: z.string().regex(/^\d+\.\d{2}$/),
  idempotency_key: z.string().optional(),
});

export async function betRoutes(fastify: FastifyInstance): Promise<void> {
  const betService = new BetService();

  // POST /api/v1/bets/place — the most critical endpoint
  fastify.post('/place', {
    preHandler: [
      requireAuth,
      idempotencyGuard('betting-service', '/bets/place'),
    ],
  }, async (request, reply) => {
    const body = PlaceBetSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({
        code: 'VALIDATION_ERROR',
        errors: body.error.flatten(),
        request_id: request.requestId,
      });
    }

    const { bet, walletBalanceAfter } = await betService.placeBet({
      userId: request.actor!.userId,
      gameSessionId: body.data.game_session_id,
      gameId: body.data.game_id,
      amount: body.data.amount,
      currency: body.data.currency,
      betType: body.data.bet_type,
      parameters: body.data.parameters,
      idempotencyKey: request.idempotencyKey!,
      ipAddress: request.ip,
    });

    return reply.code(202).send({
      bet_id: bet.betId,
      status: bet.status,
      game_id: bet.gameId,
      amount: bet.amount,
      currency: bet.currency,
      payout: bet.payout,
      wallet_balance_after: walletBalanceAfter,
      placed_at: bet.placedAt,
      settled_at: bet.settledAt,
      trace_id: request.requestId,
    });
  });

  // GET /api/v1/bets/history
  fastify.get('/history', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const query = request.query as {
      limit?: string;
      cursor?: string;
      status?: string;
    };

    const { bets, nextCursor } = await betService.getBetHistory(
      request.actor!.userId,
      {
        limit: query.limit ? parseInt(query.limit, 10) : 20,
        cursor: query.cursor,
        status: query.status as Awaited<ReturnType<typeof betService.getBetHistory>>['bets'][0]['status'] | undefined,
      },
    );

    return reply.code(200).send({
      bets: bets.map((b) => ({
        bet_id: b.betId,
        game_id: b.gameId,
        status: b.status,
        amount: b.amount,
        payout: b.payout,
        bet_type: b.betType,
        placed_at: b.placedAt,
        settled_at: b.settledAt,
      })),
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
    });
  });

  // GET /api/v1/bets/:betId
  fastify.get('/:betId', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const { betId } = request.params as { betId: string };
    const isAdmin = request.actor!.roles.includes('admin');
    const bet = await betService.getBet(betId, request.actor!.userId, isAdmin);

    return reply.code(200).send({
      bet_id: bet.betId,
      user_id: bet.userId,
      game_id: bet.gameId,
      session_id: bet.sessionId,
      status: bet.status,
      amount: bet.amount,
      currency: bet.currency,
      payout: bet.payout,
      bet_type: bet.betType,
      parameters: bet.parameters,
      risk_score: bet.riskScore,
      placed_at: bet.placedAt,
      settled_at: bet.settledAt,
    });
  });

  // POST /api/v1/bets/:betId/settle — internal use only (game engine)
  fastify.post('/:betId/settle', {
    preHandler: [requireAuth, requireRole('admin')],
  }, async (request, reply) => {
    const { betId } = request.params as { betId: string };
    const body = SettleBetSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const bet = await betService.settleBet(betId, { payout: body.data.payout });

    return reply.code(200).send({
      bet_id: bet.betId,
      status: bet.status,
      payout: bet.payout,
      settled_at: bet.settledAt,
    });
  });

  // POST /api/v1/bets/:betId/void — internal/admin only
  fastify.post('/:betId/void', {
    preHandler: [requireAuth, requireRole('admin')],
  }, async (request, reply) => {
    const { betId } = request.params as { betId: string };
    const bet = await betService.voidBet(betId, request.actor!.userId, true);
    return reply.code(200).send({ bet_id: bet.betId, status: bet.status });
  });
}
