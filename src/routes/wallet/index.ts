import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { WalletService } from '../../services/WalletService';
import { requireAuth, requireSelfOrAdmin } from '../../middleware/auth';
import { idempotencyGuard } from '../../middleware/idempotency';

const DepositSchema = z.object({
  amount: z.string().regex(/^\d+\.\d{2}$/),
  currency: z.enum(['USD', 'EUR']).default('USD'),
  payment_reference: z.string().optional(),
});

const WithdrawSchema = z.object({
  amount: z.string().regex(/^\d+\.\d{2}$/),
  currency: z.enum(['USD', 'EUR']).default('USD'),
  destination_id: z.string().optional(),
});

export async function walletRoutes(fastify: FastifyInstance): Promise<void> {
  const walletService = new WalletService();

  // GET /api/v1/wallet/:userId/balance
  fastify.get('/:userId/balance', {
    preHandler: [requireAuth, requireSelfOrAdmin],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const wallet = await walletService.getBalance(userId);
    return reply.code(200).send({
      user_id: wallet.userId,
      currency: wallet.currency,
      available: wallet.balance,
      reserved: wallet.reserved,
      total: wallet.total,
      as_of: wallet.updatedAt,
    });
  });

  // GET /api/v1/wallet/:userId/transactions
  fastify.get('/:userId/transactions', {
    preHandler: [requireAuth, requireSelfOrAdmin],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const query = request.query as { limit?: string; cursor?: string; type?: string };

    const { transactions, nextCursor } = await walletService.getTransactions(userId, {
      limit: query.limit ? parseInt(query.limit, 10) : 20,
      cursor: query.cursor,
      type: query.type,
    });

    return reply.code(200).send({
      transactions: transactions.map((tx) => ({
        tx_id: tx.txId,
        type: tx.type,
        amount: tx.amount,
        balance_after: tx.balanceAfter,
        reference_id: tx.referenceId,
        created_at: tx.createdAt,
      })),
      next_cursor: nextCursor,
      has_more: nextCursor !== null,
    });
  });

  // POST /api/v1/wallet/:userId/deposit
  fastify.post('/:userId/deposit', {
    preHandler: [
      requireAuth,
      requireSelfOrAdmin,
      idempotencyGuard('wallet-service', '/wallet/deposit'),
    ],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const body = DepositSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const tx = await walletService.deposit({
      userId,
      amount: body.data.amount,
      idempotencyKey: request.idempotencyKey!,
      paymentReference: body.data.payment_reference,
    });

    return reply.code(201).send({
      tx_id: tx.txId,
      status: 'completed',
      amount: body.data.amount,
      balance_after: tx.balanceAfter,
      created_at: tx.createdAt,
    });
  });

  // POST /api/v1/wallet/:userId/withdraw
  fastify.post('/:userId/withdraw', {
    preHandler: [
      requireAuth,
      requireSelfOrAdmin,
      idempotencyGuard('wallet-service', '/wallet/withdraw'),
    ],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const body = WithdrawSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const tx = await walletService.withdraw({
      userId,
      amount: body.data.amount,
      idempotencyKey: request.idempotencyKey!,
      destinationId: body.data.destination_id,
    });

    return reply.code(202).send({
      tx_id: tx.txId,
      status: 'pending',
      amount: body.data.amount,
      balance_after: tx.balanceAfter,
      created_at: tx.createdAt,
    });
  });
}
