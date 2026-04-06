import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { RiskService } from '../../services/RiskService';
import { requireAuth } from '../../middleware/auth';

const EvaluateSchema = z.object({
  user_id: z.string().uuid(),
  action: z.enum(['bet_place', 'login', 'withdrawal']),
  amount: z.string().optional(),
  session_id: z.string().uuid().optional(),
  device_fingerprint: z.string().optional(),
  ip_address: z.string().optional(),
});

const SignalSchema = z.object({
  user_id: z.string().uuid(),
  signal_type: z.string().min(1),
  severity: z.enum(['low', 'medium', 'high', 'critical']),
  context: z.record(z.unknown()).optional(),
});

export async function riskRoutes(fastify: FastifyInstance): Promise<void> {
  const riskService = new RiskService();

  // POST /api/v1/risk/evaluate — synchronous risk evaluation (internal only)
  fastify.post('/evaluate', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const body = EvaluateSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const result = await riskService.evaluate({
      userId: body.data.user_id,
      action: body.data.action,
      amount: body.data.amount,
      sessionId: body.data.session_id,
      deviceFingerprint: body.data.device_fingerprint,
      ipAddress: body.data.ip_address,
    });

    return reply.code(200).send(result);
  });

  // POST /api/v1/risk/signals — async signal ingestion
  fastify.post('/signals', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const body = SignalSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', errors: body.error.flatten(), request_id: request.requestId });
    }

    const signalId = await riskService.ingestSignal({
      userId: body.data.user_id,
      signalType: body.data.signal_type,
      severity: body.data.severity,
      context: body.data.context,
    });

    return reply.code(202).send({ signal_id: signalId, status: 'queued' });
  });

  // GET /api/v1/risk/users/:userId/risk-score — internal score lookup
  fastify.get('/users/:userId/risk-score', {
    preHandler: [requireAuth],
  }, async (request, reply) => {
    const { userId } = request.params as { userId: string };
    const score = await riskService.getRiskScore(userId);
    return reply.code(200).send({ user_id: userId, ...score });
  });
}
