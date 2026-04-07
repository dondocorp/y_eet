import { GameSessionService } from '../../../src/services/GameSessionService';
import { GameSessionRepository } from '../../../src/repositories/GameSessionRepository';
import { SessionNotFoundError, SessionExpiredError, ForbiddenError } from '../../../src/errors';
import { makeGameSession } from '../../factories';

jest.mock('../../../src/repositories/GameSessionRepository');
jest.useFakeTimers();

const MockSessionRepo = GameSessionRepository as jest.MockedClass<typeof GameSessionRepository>;

describe('GameSessionService', () => {
  let service: GameSessionService;
  let repo: jest.Mocked<InstanceType<typeof GameSessionRepository>>;

  beforeEach(() => {
    MockSessionRepo.mockClear();
    service = new GameSessionService();
    repo    = MockSessionRepo.mock.instances[0] as any;
  });

  afterEach(() => {
    jest.clearAllTimers();
  });

  // ── createSession ─────────────────────────────────────────────────────────

  describe('createSession', () => {
    it('creates a new session with generated seeds', async () => {
      const session = makeGameSession();
      repo.create.mockResolvedValue(session);

      const result = await service.createSession({ userId: 'usr-1', gameId: 'game_crash_v1' });

      expect(repo.create).toHaveBeenCalledWith(expect.objectContaining({
        userId: 'usr-1',
        gameId: 'game_crash_v1',
        serverSeed:     expect.any(String),
        serverSeedHash: expect.any(String),
      }));
      expect(result).toBe(session);
    });

    it('returns existing session on idempotency key match', async () => {
      const existing = makeGameSession();
      repo.findByIdempotencyKey.mockResolvedValue(existing);

      const result = await service.createSession({
        userId:         'usr-1',
        gameId:         'game_crash_v1',
        idempotencyKey: 'idem-sess-1',
      });

      expect(repo.create).not.toHaveBeenCalled();
      expect(result).toBe(existing);
    });

    it('generates unique server seeds for each session', async () => {
      repo.create.mockImplementation(async (data) => makeGameSession({ serverSeed: data.serverSeed }));

      const s1 = await service.createSession({ userId: 'usr-1', gameId: 'game_crash_v1' });
      const s2 = await service.createSession({ userId: 'usr-1', gameId: 'game_crash_v1' });

      expect(s1.serverSeed).not.toBe(s2.serverSeed);
    });
  });

  // ── getSession ────────────────────────────────────────────────────────────

  describe('getSession', () => {
    it('returns session for the owning user', async () => {
      repo.findById.mockResolvedValue(makeGameSession({ userId: 'usr-1' }));

      const result = await service.getSession('gsess-0001', 'usr-1');
      expect(result.userId).toBe('usr-1');
    });

    it('throws SessionNotFoundError when session does not exist', async () => {
      repo.findById.mockResolvedValue(null);

      await expect(service.getSession('ghost', 'usr-1')).rejects.toThrow(SessionNotFoundError);
    });

    it('throws ForbiddenError when user does not own the session', async () => {
      repo.findById.mockResolvedValue(makeGameSession({ userId: 'usr-other' }));

      await expect(service.getSession('gsess-0001', 'usr-1')).rejects.toThrow(ForbiddenError);
    });
  });

  // ── heartbeat ─────────────────────────────────────────────────────────────

  describe('heartbeat', () => {
    it('updates heartbeat timestamp', async () => {
      const session = makeGameSession({ userId: 'usr-1', status: 'active' });
      repo.findById.mockResolvedValue(session);
      repo.heartbeat.mockResolvedValue({ ...session, lastHeartbeatAt: new Date() });

      const result = await service.heartbeat('gsess-0001', 'usr-1');
      expect(repo.heartbeat).toHaveBeenCalledWith('gsess-0001');
      expect(result).toBeDefined();
    });

    it('throws SessionExpiredError when session is not active', async () => {
      repo.findById.mockResolvedValue(makeGameSession({ status: 'closed', userId: 'usr-1' }));

      await expect(service.heartbeat('gsess-0001', 'usr-1')).rejects.toThrow(SessionExpiredError);
    });

    it('throws SessionExpiredError when repo returns null', async () => {
      repo.findById.mockResolvedValue(makeGameSession({ status: 'active', userId: 'usr-1' }));
      repo.heartbeat.mockResolvedValue(null);

      await expect(service.heartbeat('gsess-0001', 'usr-1')).rejects.toThrow(SessionExpiredError);
    });
  });

  // ── validateActiveSession ─────────────────────────────────────────────────

  describe('validateActiveSession', () => {
    it('returns session when active and not expired', async () => {
      const session = makeGameSession({
        userId:    'usr-1',
        status:    'active',
        expiresAt: new Date(Date.now() + 60_000),
      });
      repo.findById.mockResolvedValue(session);

      const result = await service.validateActiveSession('gsess-0001', 'usr-1');
      expect(result).toBe(session);
    });

    it('throws SessionExpiredError when session is expired', async () => {
      repo.findById.mockResolvedValue(makeGameSession({
        userId:    'usr-1',
        status:    'active',
        expiresAt: new Date(Date.now() - 1000), // in the past
      }));
      repo.close.mockResolvedValue(null);

      await expect(service.validateActiveSession('gsess-0001', 'usr-1')).rejects.toThrow(SessionExpiredError);
    });

    it('throws ForbiddenError when userId does not match', async () => {
      repo.findById.mockResolvedValue(makeGameSession({ userId: 'usr-other', status: 'active' }));

      await expect(service.validateActiveSession('gsess-0001', 'usr-1')).rejects.toThrow(ForbiddenError);
    });
  });

  // ── closeSession ──────────────────────────────────────────────────────────

  describe('closeSession', () => {
    it('closes the session', async () => {
      const session = makeGameSession({ userId: 'usr-1' });
      repo.findById.mockResolvedValue(session);
      repo.close.mockResolvedValue({ ...session, status: 'closed' });

      const result = await service.closeSession('gsess-0001', 'usr-1');
      expect(repo.close).toHaveBeenCalledWith('gsess-0001', 'usr-1');
      expect(result.status).toBe('closed');
    });

    it('returns original session when already closed (idempotent)', async () => {
      const session = makeGameSession({ userId: 'usr-1', status: 'closed' });
      repo.findById.mockResolvedValue(session);
      repo.close.mockResolvedValue(null); // already closed

      const result = await service.closeSession('gsess-0001', 'usr-1');
      expect(result).toBe(session);
    });
  });

  // ── revealServerSeed ──────────────────────────────────────────────────────

  describe('revealServerSeed', () => {
    it('returns seeds for a closed session', async () => {
      repo.findById.mockResolvedValue(makeGameSession({
        userId:     'usr-1',
        status:     'closed',
        serverSeed: 'secret-seed',
      }));

      const result = await service.revealServerSeed('gsess-0001', 'usr-1');
      expect(result.serverSeed).toBe('secret-seed');
      expect(result.serverSeedHash).toBeDefined();
    });

    it('throws ForbiddenError when session is still active', async () => {
      repo.findById.mockResolvedValue(makeGameSession({ userId: 'usr-1', status: 'active' }));

      await expect(service.revealServerSeed('gsess-0001', 'usr-1')).rejects.toThrow(ForbiddenError);
    });
  });

  // ── computeOutcome ────────────────────────────────────────────────────────

  describe('computeOutcome', () => {
    it('returns a float between 0 and 1', () => {
      const result = service.computeOutcome('server-seed', 'client-seed', 'nonce-1');
      expect(result).toBeGreaterThanOrEqual(0);
      expect(result).toBeLessThanOrEqual(1);
    });

    it('is deterministic for the same inputs', () => {
      const r1 = service.computeOutcome('seed', 'client', 'n1');
      const r2 = service.computeOutcome('seed', 'client', 'n1');
      expect(r1).toBe(r2);
    });

    it('produces different values for different nonces', () => {
      const r1 = service.computeOutcome('seed', 'client', 'nonce-1');
      const r2 = service.computeOutcome('seed', 'client', 'nonce-2');
      expect(r1).not.toBe(r2);
    });
  });
});
