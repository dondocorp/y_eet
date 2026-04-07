/**
 * idempotency.ts creates `const repo = new IdempotencyRepository()` at module level.
 * To control that instance we must set up the mock BEFORE importing the middleware,
 * and retain the instance reference across all tests ourselves.
 */

// ── 1. Set up the IdempotencyRepository mock ─────────────────────────────────
const mockGet = jest.fn();
const mockSet = jest.fn();

jest.mock('../../../src/repositories/IdempotencyRepository', () => ({
  IdempotencyRepository: jest.fn().mockImplementation(() => ({
    get: mockGet,
    set: mockSet,
  })),
}));

// ── 2. Now import the middleware (repo is created here with our mocks) ────────
import { idempotencyGuard, persistIdempotencyResponse, IDEMPOTENCY_META } from '../../../src/middleware/idempotency';

// ─────────────────────────────────────────────────────────────────────────────

const makeRequest = (overrides: Record<string, unknown> = {}) => ({
  headers:        {},
  requestId:      'req-001',
  idempotencyKey: undefined,
  ...overrides,
});

const makeReply = () => {
  const reply: Record<string, jest.Mock> = {
    code:   jest.fn(),
    send:   jest.fn(),
    header: jest.fn(),
  };
  reply.code.mockReturnValue(reply);
  reply.send.mockReturnValue(reply);
  reply.header.mockReturnValue(reply);
  return reply;
};

describe('idempotency middleware', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockSet.mockReset();
  });

  // ── idempotencyGuard ───────────────────────────────────────────────────────

  describe('idempotencyGuard', () => {
    it('returns 400 when Idempotency-Key header is missing', async () => {
      const handler = idempotencyGuard('wallet', 'deposit');
      const request = makeRequest({ headers: {} });
      const reply   = makeReply();

      await handler(request as any, reply as any);

      expect(reply.code).toHaveBeenCalledWith(400);
      expect(reply.send).toHaveBeenCalledWith(expect.objectContaining({
        code: 'MISSING_IDEMPOTENCY_KEY',
      }));
    });

    it('attaches IDEMPOTENCY_META to request when key is new', async () => {
      mockGet.mockResolvedValue(null);
      const handler = idempotencyGuard('wallet', 'deposit', 24);
      const request = makeRequest({ headers: { 'idempotency-key': 'key-123' } });
      const reply   = makeReply();

      await handler(request as any, reply as any);

      const meta = (request as any)[IDEMPOTENCY_META];
      expect(meta).toEqual({ key: 'key-123', service: 'wallet', endpoint: 'deposit', ttlHours: 24 });
    });

    it('replays cached response and sets replay header on key hit', async () => {
      mockGet.mockResolvedValue({ statusCode: 200, responseBody: { balance: '1000.00' } });

      const handler = idempotencyGuard('wallet', 'deposit');
      const request = makeRequest({ headers: { 'idempotency-key': 'existing-key' } });
      const reply   = makeReply();

      await handler(request as any, reply as any);

      expect(reply.header).toHaveBeenCalledWith('X-Idempotency-Replay', 'true');
      expect(reply.code).toHaveBeenCalledWith(200);
      expect(reply.send).toHaveBeenCalledWith({ balance: '1000.00' });
    });
  });

  // ── persistIdempotencyResponse ─────────────────────────────────────────────

  describe('persistIdempotencyResponse', () => {
    it('persists response when IDEMPOTENCY_META is set and status is 2xx', async () => {
      mockSet.mockResolvedValue(undefined);
      const request = makeRequest();
      (request as any)[IDEMPOTENCY_META] = {
        key:      'key-abc',
        service:  'wallet',
        endpoint: 'deposit',
        ttlHours: 24,
      };

      await persistIdempotencyResponse(request as any, 200, '{"balance":"500.00"}');

      expect(mockSet).toHaveBeenCalledWith(
        'key-abc', 'wallet', 'deposit', 200,
        { balance: '500.00' },
        24,
      );
    });

    it('does nothing when IDEMPOTENCY_META is not set', async () => {
      const request = makeRequest();

      await persistIdempotencyResponse(request as any, 200, '{}');

      expect(mockSet).not.toHaveBeenCalled();
    });

    it('does not persist 5xx responses', async () => {
      const request = makeRequest();
      (request as any)[IDEMPOTENCY_META] = {
        key: 'key-err', service: 'wallet', endpoint: 'deposit', ttlHours: 24,
      };

      await persistIdempotencyResponse(request as any, 500, '{"error":"server error"}');

      expect(mockSet).not.toHaveBeenCalled();
    });

    it('handles non-JSON payload gracefully', async () => {
      mockSet.mockResolvedValue(undefined);
      const request = makeRequest();
      (request as any)[IDEMPOTENCY_META] = {
        key: 'key-raw', service: 'wallet', endpoint: 'deposit', ttlHours: 1,
      };

      await expect(
        persistIdempotencyResponse(request as any, 200, 'not-json'),
      ).resolves.toBeUndefined();
    });
  });
});
