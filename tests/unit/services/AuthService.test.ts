import bcrypt from 'bcryptjs';
import { AuthService } from '../../../src/services/AuthService';
import { UserRepository } from '../../../src/repositories/UserRepository';
import { WalletRepository } from '../../../src/repositories/WalletRepository';
import { RiskRepository } from '../../../src/repositories/RiskRepository';
import { pool } from '../../../src/db/pool';
import { UnauthorizedError, UserSuspendedError } from '../../../src/errors';
import { makeUser, makeRiskProfile } from '../../factories';

jest.mock('../../../src/repositories/UserRepository');
jest.mock('../../../src/repositories/WalletRepository');
jest.mock('../../../src/repositories/RiskRepository');
jest.mock('../../../src/db/pool', () => ({
  pool: { query: jest.fn(), connect: jest.fn() },
}));

const MockUserRepo   = UserRepository   as jest.MockedClass<typeof UserRepository>;
const MockWalletRepo = WalletRepository as jest.MockedClass<typeof WalletRepository>;
const MockRiskRepo   = RiskRepository   as jest.MockedClass<typeof RiskRepository>;
const mockPool       = pool as jest.Mocked<typeof pool>;

const makeFastify = () => ({
  jwt: {
    sign:   jest.fn().mockReturnValue('signed-token'),
    verify: jest.fn(),
    decode: jest.fn(),
  },
});

describe('AuthService', () => {
  let service: AuthService;
  let mockFastify: ReturnType<typeof makeFastify>;
  let userRepo: jest.Mocked<InstanceType<typeof UserRepository>>;
  let riskRepo: jest.Mocked<InstanceType<typeof RiskRepository>>;
  let walletRepo: jest.Mocked<InstanceType<typeof WalletRepository>>;

  beforeEach(() => {
    MockUserRepo.mockClear();
    MockWalletRepo.mockClear();
    MockRiskRepo.mockClear();

    mockFastify = makeFastify();
    service = new AuthService();
    service.setFastify(mockFastify as any);

    userRepo   = MockUserRepo.mock.instances[0]   as any;
    walletRepo = MockWalletRepo.mock.instances[0] as any;
    riskRepo   = MockRiskRepo.mock.instances[0]   as any;

    // Stub pool.connect to return a fake client
    const fakeClient = {
      query:   jest.fn().mockResolvedValue({ rows: [] }),
      release: jest.fn(),
    };
    (mockPool.connect as jest.Mock).mockResolvedValue(fakeClient);
    (mockPool.query   as jest.Mock).mockResolvedValue({ rows: [] });
  });

  // ── login ──────────────────────────────────────────────────────────────────

  describe('login', () => {
    it('returns a token pair for valid credentials', async () => {
      const user = makeUser();
      const hash = await bcrypt.hash('Password123!', 1);
      userRepo.findByEmail.mockResolvedValue({ ...user, passwordHash: hash });
      riskRepo.getProfile.mockResolvedValue(makeRiskProfile());

      const result = await service.login('player1@y_eet.com', 'Password123!');

      expect(result.accessToken).toBe('signed-token');
      expect(result.sessionId).toBeTruthy();
      expect(mockFastify.jwt.sign).toHaveBeenCalledTimes(2); // access + refresh
    });

    it('throws UnauthorizedError when user is not found', async () => {
      userRepo.findByEmail.mockResolvedValue(null);

      await expect(service.login('unknown@y_eet.com', 'any')).rejects.toThrow(UnauthorizedError);
    });

    it('throws UnauthorizedError when password is wrong', async () => {
      const hash = await bcrypt.hash('correctPassword', 1);
      userRepo.findByEmail.mockResolvedValue(makeUser({ passwordHash: hash }));

      await expect(service.login('player1@y_eet.com', 'wrongPassword')).rejects.toThrow(UnauthorizedError);
    });

    it('throws UserSuspendedError when account is suspended', async () => {
      const hash = await bcrypt.hash('Password123!', 1);
      userRepo.findByEmail.mockResolvedValue(makeUser({ status: 'suspended', passwordHash: hash }));

      await expect(service.login('player1@y_eet.com', 'Password123!')).rejects.toThrow(UserSuspendedError);
    });

    it('throws UserSuspendedError when account is self-excluded', async () => {
      const hash = await bcrypt.hash('Password123!', 1);
      userRepo.findByEmail.mockResolvedValue(makeUser({ status: 'self_excluded', passwordHash: hash }));

      await expect(service.login('player1@y_eet.com', 'Password123!')).rejects.toThrow(UserSuspendedError);
    });

    it('obscures reason — user-not-found throws same error as wrong password', async () => {
      userRepo.findByEmail.mockResolvedValue(null);

      const notFound = service.login('nobody@y_eet.com', 'x');
      await expect(notFound).rejects.toThrow('Invalid credentials');
    });
  });

  // ── register ───────────────────────────────────────────────────────────────

  describe('register', () => {
    it('creates user, wallet, and risk profile, returns token pair', async () => {
      const user = makeUser();
      userRepo.create.mockResolvedValue(user);
      walletRepo.create.mockResolvedValue(undefined as any);
      riskRepo.upsertProfile.mockResolvedValue(makeRiskProfile());
      riskRepo.getProfile.mockResolvedValue(makeRiskProfile());

      const result = await service.register({
        email:    'new@y_eet.com',
        username: 'newuser',
        password: 'Password123!',
      });

      expect(userRepo.create).toHaveBeenCalledWith(
        expect.objectContaining({ email: 'new@y_eet.com', username: 'newuser' }),
      );
      expect(walletRepo.create).toHaveBeenCalledWith(user.userId);
      expect(riskRepo.upsertProfile).toHaveBeenCalledWith(
        expect.objectContaining({ userId: user.userId }),
      );
      expect(result.tokens.accessToken).toBe('signed-token');
    });

    it('hashes the password before storing it', async () => {
      userRepo.create.mockImplementation(async (data) => {
        // Assert the password was hashed, not stored in plain text
        expect(data.passwordHash).not.toBe('Password123!');
        expect(data.passwordHash).toMatch(/^\$2[ab]\$/);
        return makeUser();
      });
      walletRepo.create.mockResolvedValue(undefined as any);
      riskRepo.upsertProfile.mockResolvedValue(makeRiskProfile());
      riskRepo.getProfile.mockResolvedValue(makeRiskProfile());

      await service.register({ email: 'x@y.com', username: 'xyz', password: 'Password123!' });
    });
  });

  // ── refresh ────────────────────────────────────────────────────────────────

  describe('refresh', () => {
    it('throws when jwt.decode returns null', async () => {
      mockFastify.jwt.decode.mockReturnValue(null);

      await expect(service.refresh('bad-token')).rejects.toThrow(UnauthorizedError);
    });

    it('throws when session is revoked', async () => {
      mockFastify.jwt.decode.mockReturnValue({ sub: 'usr-1', sessionId: 'sess-1' });

      const hash = await bcrypt.hash('token', 1);
      const fakeClient = {
        query: jest.fn()
          .mockResolvedValueOnce({ rows: [] }) // BEGIN
          .mockResolvedValueOnce({ rows: [{ session_id: 'sess-1', user_id: 'usr-1', refresh_token_hash: hash, used_at: null, revoked_at: new Date(), expires_at: new Date(Date.now() + 99999) }] })
          .mockResolvedValue({ rows: [] }),
        release: jest.fn(),
      };
      (mockPool.connect as jest.Mock).mockResolvedValue(fakeClient);

      await expect(service.refresh('some-token')).rejects.toThrow(UnauthorizedError);
    });
  });

  // ── validateSession ────────────────────────────────────────────────────────

  describe('validateSession', () => {
    it('returns valid=false when jwt.verify throws', async () => {
      mockFastify.jwt.verify.mockImplementation(() => { throw new Error('expired'); });

      const result = await service.validateSession('bad-token');
      expect(result.valid).toBe(false);
    });

    it('returns valid=false when session is revoked in DB', async () => {
      mockFastify.jwt.verify.mockReturnValue({ sub: 'usr-1', sessionId: 'sess-1', roles: ['player'], riskTier: 'standard' });
      (mockPool.query as jest.Mock).mockResolvedValue({ rows: [{ revoked_at: new Date() }] });

      const result = await service.validateSession('valid-jwt');
      expect(result.valid).toBe(false);
    });

    it('returns valid=true when session exists and is not revoked', async () => {
      mockFastify.jwt.verify.mockReturnValue({ sub: 'usr-1', sessionId: 'sess-1', roles: ['player'], riskTier: 'standard' });
      (mockPool.query as jest.Mock).mockResolvedValue({ rows: [{ revoked_at: null }] });

      const result = await service.validateSession('valid-jwt');
      expect(result.valid).toBe(true);
      expect(result.userId).toBe('usr-1');
    });
  });

  // ── revoke ─────────────────────────────────────────────────────────────────

  describe('revoke', () => {
    it('issues an UPDATE query for the given session', async () => {
      (mockPool.query as jest.Mock).mockResolvedValue({ rowCount: 1 });

      await service.revoke('sess-1', 'usr-1');

      expect(mockPool.query).toHaveBeenCalledWith(
        expect.stringContaining('UPDATE sessions'),
        ['sess-1', 'usr-1'],
      );
    });
  });
});
