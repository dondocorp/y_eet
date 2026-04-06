import Fastify, { FastifyInstance } from 'fastify';
import fastifyJwt from '@fastify/jwt';
import fastifyHelmet from '@fastify/helmet';
import fastifyCors from '@fastify/cors';
import fastifySensible from '@fastify/sensible';
import fastifyRateLimit from '@fastify/rate-limit';
import { context, trace, isSpanContextValid } from '@opentelemetry/api';

import { config } from './config';
import { registerRequestMiddleware } from './middleware/requestId';
import { persistIdempotencyResponse } from './middleware/idempotency';
import { AppError } from './errors';

import { authRoutes } from './routes/auth';
import { walletRoutes } from './routes/wallet';
import { betRoutes } from './routes/bets';
import { gameRoutes } from './routes/games';
import { riskRoutes } from './routes/risk';
import { configRoutes } from './routes/config';
import { healthRoutes } from './routes/health';
import { userRoutes } from './routes/users';
import { adminRoutes } from './routes/admin';

export async function buildApp(): Promise<FastifyInstance> {
  const fastify = Fastify({
    logger: {
      level: config.LOG_LEVEL,
      formatters: {
        level(label) { return { level: label }; },
      },
      timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
      mixin() {
        const span = trace.getSpan(context.active());
        if (span) {
          const ctx = span.spanContext();
          if (isSpanContextValid(ctx)) {
            return { trace_id: ctx.traceId, span_id: ctx.spanId };
          }
        }
        return {};
      },
      serializers: {
        req(req) {
          return {
            method: req.method,
            url: req.url,
            request_id: (req as unknown as { requestId?: string }).requestId,
            synthetic: (req.headers?.['x-synthetic'] === 'true'),
          };
        },
        res(res) {
          return { status_code: res.statusCode };
        },
      },
    },
    trustProxy: true,
    requestTimeout: 30_000,
    bodyLimit: 1_048_576, // 1MB
  });

  // ── Security ───────────────────────────────────────────────────────────────
  await fastify.register(fastifyHelmet, {
    contentSecurityPolicy: false, // API only — no HTML
  });

  await fastify.register(fastifyCors, {
    origin: config.NODE_ENV === 'production' ? ['https://y_eet.com', 'https://app.y_eet.com'] : true,
    credentials: true,
  });

  // ── Core plugins ───────────────────────────────────────────────────────────
  await fastify.register(fastifySensible);

  await fastify.register(fastifyJwt, {
    secret: config.JWT_SECRET,
    sign: { algorithm: 'HS256', expiresIn: config.JWT_EXPIRY },
  });

  await fastify.register(fastifyRateLimit, {
    max: config.RATE_LIMIT_MAX,
    timeWindow: config.RATE_LIMIT_WINDOW_MS,
    keyGenerator: (req) => {
      // Rate limit by user ID if authenticated, otherwise by IP
      const auth = req.headers.authorization;
      if (auth) {
        try {
          const payload = fastify.jwt.decode<{ sub: string }>(auth.replace('Bearer ', ''));
          if (payload?.sub) return `user:${payload.sub}`;
        } catch { /* fall through */ }
      }
      return req.ip;
    },
    errorResponseBuilder: (_req, context) => ({
      code: 'RATE_LIMITED',
      message: 'Too many requests',
      retry_after_ms: context.after,
    }),
  });

  // ── Request middleware ─────────────────────────────────────────────────────
  registerRequestMiddleware(fastify);

  // ── Idempotency response caching ───────────────────────────────────────────
  fastify.addHook('onSend', async (request, reply, payload) => {
    await persistIdempotencyResponse(request, reply.statusCode, payload);
    return payload;
  });

  // ── Global error handler ───────────────────────────────────────────────────
  fastify.setErrorHandler((error, request, reply) => {
    // Attach OTEL trace_id to every error response for correlation
    const activeSpan = trace.getSpan(context.active());
    const otelTraceId = activeSpan && isSpanContextValid(activeSpan.spanContext())
      ? activeSpan.spanContext().traceId
      : undefined;
    const traceId = otelTraceId ?? request.requestId;

    // Known application errors
    if (error instanceof AppError) {
      return reply.code(error.statusCode).send({
        code: error.code,
        message: error.message,
        details: error.details,
        request_id: request.requestId,
        trace_id: traceId,
      });
    }

    // Zod/validation errors bubbled from Fastify schema
    if (error.validation) {
      return reply.code(400).send({
        code: 'VALIDATION_ERROR',
        message: 'Request validation failed',
        errors: error.validation,
        request_id: request.requestId,
        trace_id: traceId,
      });
    }

    // JWT errors
    if (error.name === 'JsonWebTokenError' || error.name === 'TokenExpiredError') {
      return reply.code(401).send({
        code: 'UNAUTHORIZED',
        message: 'Invalid or expired token',
        request_id: request.requestId,
        trace_id: traceId,
      });
    }

    // Postgres unique constraint violations
    if ((error as NodeJS.ErrnoException & { code?: string }).code === '23505') {
      return reply.code(409).send({
        code: 'CONFLICT',
        message: 'Duplicate entry',
        request_id: request.requestId,
        trace_id: traceId,
      });
    }

    // Unknown errors — log and return 500
    fastify.log.error({
      err: error,
      request_id: request.requestId,
      trace_id: traceId,
      url: request.url,
      method: request.method,
    });

    return reply.code(500).send({
      code: 'INTERNAL_ERROR',
      message: config.NODE_ENV === 'production' ? 'Internal server error' : error.message,
      request_id: request.requestId,
      trace_id: traceId,
    });
  });

  // ── Routes ─────────────────────────────────────────────────────────────────
  fastify.register(healthRoutes, { prefix: '/health' });

  fastify.register(authRoutes, { prefix: '/api/v1/auth' });
  fastify.register(userRoutes, { prefix: '/api/v1/users' });
  fastify.register(walletRoutes, { prefix: '/api/v1/wallet' });
  fastify.register(betRoutes, { prefix: '/api/v1/bets' });
  fastify.register(gameRoutes, { prefix: '/api/v1/games' });
  fastify.register(riskRoutes, { prefix: '/api/v1/risk' });
  fastify.register(configRoutes, { prefix: '/api/v1/config' });
  fastify.register(adminRoutes, { prefix: '/_internal' });

  // Root
  fastify.get('/', async (_req, reply) => {
    return reply.code(200).send({ service: config.SERVICE_NAME, version: config.SERVICE_VERSION });
  });

  return fastify;
}
