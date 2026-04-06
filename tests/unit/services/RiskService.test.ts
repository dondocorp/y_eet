import { RiskService } from '../../../src/services/RiskService';
import { RiskRepository } from '../../../src/repositories/RiskRepository';
import { makeRiskProfile } from '../../factories';

jest.mock('../../../src/repositories/RiskRepository');
jest.mock('../../../src/repositories/ConfigRepository');

// Stub opossum so tests run synchronously without the real circuit breaker overhead
jest.mock('opossum', () => {
  return jest.fn().mockImplementation((fn: Function) => ({
    fire: (...args: unknown[]) => fn(...args),
    on: jest.fn(),
    fallback: jest.fn(),
  }));
});

const MockRiskRepo = RiskRepository as jest.MockedClass<typeof RiskRepository>;

describe('RiskService', () => {
  let service: RiskService;
  let riskRepo: jest.Mocked<InstanceType<typeof RiskRepository>>;

  beforeEach(() => {
    MockRiskRepo.mockClear();
    service  = new RiskService();
    riskRepo = MockRiskRepo.mock.instances[0] as any;

    // Safe defaults
    riskRepo.getProfile.mockResolvedValue(makeRiskProfile({ riskScore: 0, riskTier: 'low' }));
    riskRepo.countBetsInWindow.mockResolvedValue(0);
    riskRepo.sumLossesToday.mockResolvedValue('0.00');
    riskRepo.upsertProfile.mockResolvedValue(makeRiskProfile());
    riskRepo.ingestSignal.mockResolvedValue('sig-001');
  });

  // ── evaluate ──────────────────────────────────────────────────────────────

  describe('evaluate', () => {
    it('returns allow decision for low-risk bet', async () => {
      const result = await service.evaluate({
        userId: 'usr-1',
        action: 'bet_place',
        amount: '10.00',
      });

      expect(result.decision).toBe('allow');
      expect(result.riskScore).toBeLessThan(60);
    });

    it('adds high_value_bet flag for stake >= 1000', async () => {
      const result = await service.evaluate({
        userId: 'usr-1',
        action: 'bet_place',
        amount: '1000.00',
      });

      expect(result.flags).toContain('high_value_bet');
      expect(result.riskScore).toBeGreaterThanOrEqual(20);
    });

    it('flags high bet velocity when >30 bets in 60s', async () => {
      riskRepo.countBetsInWindow.mockResolvedValue(35);

      const result = await service.evaluate({
        userId: 'usr-1',
        action: 'bet_place',
        amount: '10.00',
      });

      expect(result.flags).toContain('high_bet_velocity');
    });

    it('returns reject decision for blocked risk tier', async () => {
      riskRepo.getProfile.mockResolvedValue(makeRiskProfile({ riskScore: 100, riskTier: 'blocked' }));

      const result = await service.evaluate({
        userId: 'usr-1',
        action: 'bet_place',
        amount: '10.00',
      });

      expect(result.decision).toBe('reject');
      expect(result.flags).toContain('account_blocked');
    });

    it('flags approaching_loss_limit when losses near threshold', async () => {
      riskRepo.getProfile.mockResolvedValue(makeRiskProfile({ riskScore: 5 }));
      riskRepo.sumLossesToday.mockResolvedValue('850.00'); // 850 + 50 = 900 > 1000*0.8=800

      const result = await service.evaluate({
        userId: 'usr-1',
        action: 'bet_place',
        amount: '50.00',
      });

      expect(result.flags).toContain('approaching_loss_limit');
    });
  });

  // ── getRiskScore ──────────────────────────────────────────────────────────

  describe('getRiskScore', () => {
    it('returns profile data when profile exists', async () => {
      riskRepo.getProfile.mockResolvedValue(makeRiskProfile({ riskScore: 42, riskTier: 'elevated', flags: ['high_value_bet'] }));

      const result = await service.getRiskScore('usr-1');

      expect(result.riskScore).toBe(42);
      expect(result.riskTier).toBe('elevated');
      expect(result.flags).toContain('high_value_bet');
    });

    it('returns safe defaults when no profile exists', async () => {
      riskRepo.getProfile.mockResolvedValue(null);

      const result = await service.getRiskScore('usr-1');

      expect(result.riskScore).toBe(0);
      expect(result.riskTier).toBe('standard');
      expect(result.flags).toEqual([]);
    });
  });

  // ── ingestSignal ──────────────────────────────────────────────────────────

  describe('ingestSignal', () => {
    it('delegates to repo with all fields', async () => {
      await service.ingestSignal({
        userId:     'usr-1',
        signalType: 'manual_review',
        severity:   'high',
        context:    { reason: 'suspicious_activity' },
      });

      expect(riskRepo.ingestSignal).toHaveBeenCalledWith(expect.objectContaining({
        userId:     'usr-1',
        signalType: 'manual_review',
        severity:   'high',
        context:    { reason: 'suspicious_activity' },
      }));
    });
  });
});
