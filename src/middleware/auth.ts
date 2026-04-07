import { FastifyRequest, FastifyReply } from 'fastify';
import { UnauthorizedError, ForbiddenError } from '../errors';

/**
 * Fastify preHandler — validates JWT and populates request.actor.
 * JWT validation is handled by @fastify/jwt registered in app.ts.
 */
export async function requireAuth(request: FastifyRequest, _reply: FastifyReply): Promise<void> {
  try {
    await request.jwtVerify();
    const payload = request.user as {
      sub: string;
      sessionId: string;
      roles: string[];
      riskTier: string;
    };

    request.actor = {
      userId: payload.sub,
      sessionId: payload.sessionId,
      roles: payload.roles ?? ['player'],
    };
  } catch {
    throw new UnauthorizedError('Invalid or expired token');
  }
}

/**
 * Fastify preHandler — requires the actor to have a specific role.
 */
export function requireRole(...roles: string[]) {
  return async (request: FastifyRequest, _reply: FastifyReply): Promise<void> => {
    if (!request.actor) throw new UnauthorizedError();
    const hasRole = roles.some((role) => request.actor!.roles.includes(role));
    if (!hasRole) throw new ForbiddenError(`Required role: ${roles.join(' or ')}`);
  };
}

/**
 * Fastify preHandler — the requesting user must be the target user, or have admin role.
 * Assumes route param is :userId.
 */
export async function requireSelfOrAdmin(request: FastifyRequest, _reply: FastifyReply): Promise<void> {
  if (!request.actor) throw new UnauthorizedError();
  const params = request.params as { userId?: string };
  const isOwner = params.userId === request.actor.userId;
  const isAdmin = request.actor.roles.includes('admin');
  if (!isOwner && !isAdmin) throw new ForbiddenError('Access denied');
}
