import { FastifyInstance } from 'fastify';
import { z } from 'zod';
import { AuthService } from '../../services/AuthService';
import { requireAuth } from '../../middleware/auth';

const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
  device_fingerprint: z.string().optional(),
});

const RegisterSchema = z.object({
  email: z.string().email(),
  username: z.string().min(3).max(30).regex(/^[a-zA-Z0-9_]+$/),
  password: z.string().min(8),
  jurisdiction: z.string().optional(),
});

const RefreshSchema = z.object({
  refresh_token: z.string(),
});

export async function authRoutes(fastify: FastifyInstance): Promise<void> {
  const authService = new AuthService();
  authService.setFastify(fastify);

  // POST /api/v1/auth/token — login
  fastify.post('/token', async (request, reply) => {
    const body = LoginSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', message: 'Invalid input', errors: body.error.flatten(), request_id: request.requestId });
    }

    const tokens = await authService.login(
      body.data.email,
      body.data.password,
      body.data.device_fingerprint,
    );

    return reply.code(200).send({
      access_token: tokens.accessToken,
      refresh_token: tokens.refreshToken,
      expires_in: tokens.expiresIn,
      token_type: 'Bearer',
      session_id: tokens.sessionId,
    });
  });

  // POST /api/v1/auth/register
  fastify.post('/register', async (request, reply) => {
    const body = RegisterSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', message: 'Invalid input', errors: body.error.flatten(), request_id: request.requestId });
    }

    const { user, tokens } = await authService.register(body.data);

    return reply.code(201).send({
      user_id: user.userId,
      email: user.email,
      username: user.username,
      access_token: tokens.accessToken,
      refresh_token: tokens.refreshToken,
      expires_in: tokens.expiresIn,
      session_id: tokens.sessionId,
    });
  });

  // POST /api/v1/auth/refresh
  fastify.post('/refresh', async (request, reply) => {
    const body = RefreshSchema.safeParse(request.body);
    if (!body.success) {
      return reply.code(400).send({ code: 'VALIDATION_ERROR', message: 'refresh_token required', request_id: request.requestId });
    }

    const tokens = await authService.refresh(body.data.refresh_token);
    return reply.code(200).send({
      access_token: tokens.accessToken,
      expires_in: tokens.expiresIn,
    });
  });

  // POST /api/v1/auth/revoke — logout
  fastify.post('/revoke', { preHandler: [requireAuth] }, async (request, reply) => {
    await authService.revoke(request.actor!.sessionId, request.actor!.userId);
    return reply.code(204).send();
  });

  // GET /api/v1/auth/session/validate — internal service use
  fastify.get('/session/validate', async (request, reply) => {
    const token = (request.headers['authorization'] ?? '').replace('Bearer ', '');
    if (!token) return reply.code(401).send({ valid: false });
    const result = await authService.validateSession(token);
    return reply.code(result.valid ? 200 : 401).send(result);
  });
}
