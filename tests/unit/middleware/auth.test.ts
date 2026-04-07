import { requireAuth, requireRole, requireSelfOrAdmin } from '../../../src/middleware/auth';
import { UnauthorizedError, ForbiddenError } from '../../../src/errors';

const makeRequest = (overrides: Record<string, unknown> = {}) => ({
  jwtVerify: jest.fn(),
  user:      null,
  actor:     undefined,
  params:    {},
  ...overrides,
});

const makeReply = () => ({
  code: jest.fn().mockReturnThis(),
  send: jest.fn().mockReturnThis(),
});

describe('auth middleware', () => {
  // ── requireAuth ────────────────────────────────────────────────────────────

  describe('requireAuth', () => {
    it('populates request.actor on valid JWT', async () => {
      const request = makeRequest({
        jwtVerify: jest.fn().mockResolvedValue(undefined),
        user: {
          sub:       'usr-1',
          sessionId: 'sess-1',
          roles:     ['player'],
          riskTier:  'standard',
        },
      });
      const reply = makeReply();

      await requireAuth(request as any, reply as any);

      expect(request.actor).toEqual({ userId: 'usr-1', sessionId: 'sess-1', roles: ['player'] });
    });

    it('defaults to [player] role when roles is missing from token', async () => {
      const request = makeRequest({
        jwtVerify: jest.fn().mockResolvedValue(undefined),
        user: { sub: 'usr-1', sessionId: 'sess-1' }, // no roles
      });

      await requireAuth(request as any, makeReply() as any);

      expect(request.actor!.roles).toEqual(['player']);
    });

    it('throws UnauthorizedError when jwtVerify throws', async () => {
      const request = makeRequest({
        jwtVerify: jest.fn().mockRejectedValue(new Error('expired')),
      });

      await expect(requireAuth(request as any, makeReply() as any)).rejects.toThrow(UnauthorizedError);
    });
  });

  // ── requireRole ────────────────────────────────────────────────────────────

  describe('requireRole', () => {
    it('passes through when actor has the required role', async () => {
      const request = makeRequest({ actor: { userId: 'usr-1', roles: ['admin'] } });

      await expect(requireRole('admin')(request as any, makeReply() as any)).resolves.toBeUndefined();
    });

    it('throws ForbiddenError when actor lacks the role', async () => {
      const request = makeRequest({ actor: { userId: 'usr-1', roles: ['player'] } });

      await expect(requireRole('admin')(request as any, makeReply() as any)).rejects.toThrow(ForbiddenError);
    });

    it('allows any of the listed roles to pass', async () => {
      const request = makeRequest({ actor: { userId: 'usr-1', roles: ['support'] } });

      await expect(
        requireRole('admin', 'support')(request as any, makeReply() as any),
      ).resolves.toBeUndefined();
    });

    it('throws UnauthorizedError when actor is not set', async () => {
      const request = makeRequest({ actor: undefined });

      await expect(requireRole('admin')(request as any, makeReply() as any)).rejects.toThrow(UnauthorizedError);
    });
  });

  // ── requireSelfOrAdmin ─────────────────────────────────────────────────────

  describe('requireSelfOrAdmin', () => {
    it('passes when userId param matches actor', async () => {
      const request = makeRequest({
        actor:  { userId: 'usr-1', roles: ['player'] },
        params: { userId: 'usr-1' },
      });

      await expect(requireSelfOrAdmin(request as any, makeReply() as any)).resolves.toBeUndefined();
    });

    it('passes when actor is admin regardless of userId param', async () => {
      const request = makeRequest({
        actor:  { userId: 'admin-1', roles: ['player', 'admin'] },
        params: { userId: 'usr-other' },
      });

      await expect(requireSelfOrAdmin(request as any, makeReply() as any)).resolves.toBeUndefined();
    });

    it('throws ForbiddenError when userId does not match and not admin', async () => {
      const request = makeRequest({
        actor:  { userId: 'usr-1', roles: ['player'] },
        params: { userId: 'usr-other' },
      });

      await expect(requireSelfOrAdmin(request as any, makeReply() as any)).rejects.toThrow(ForbiddenError);
    });

    it('throws UnauthorizedError when actor is not set', async () => {
      const request = makeRequest({ actor: undefined, params: { userId: 'usr-1' } });

      await expect(requireSelfOrAdmin(request as any, makeReply() as any)).rejects.toThrow(UnauthorizedError);
    });
  });
});
