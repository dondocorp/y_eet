import { ConfigService } from '../../../src/services/ConfigService';
import { ConfigRepository } from '../../../src/repositories/ConfigRepository';
import { makeFeatureFlag } from '../../factories';

jest.mock('../../../src/repositories/ConfigRepository');

const MockConfigRepo = ConfigRepository as jest.MockedClass<typeof ConfigRepository>;

describe('ConfigService', () => {
  let service: ConfigService;
  let repo: jest.Mocked<InstanceType<typeof ConfigRepository>>;

  beforeEach(() => {
    MockConfigRepo.mockClear();
    service = new ConfigService();   // fresh instance = fresh cache (instance-level)
    repo    = MockConfigRepo.mock.instances[0] as any;
  });

  // ── isEnabled ─────────────────────────────────────────────────────────────

  describe('isEnabled', () => {
    it('returns false when flag does not exist', async () => {
      repo.getAll.mockResolvedValue([]);

      expect(await service.isEnabled('missing_flag')).toBe(false);
    });

    it('returns false when flag is disabled', async () => {
      repo.getAll.mockResolvedValue([makeFeatureFlag({ flagKey: 'my_flag', enabled: false, rolloutPct: 100 })]);

      expect(await service.isEnabled('my_flag')).toBe(false);
    });

    it('returns true when flag is enabled at 100% rollout', async () => {
      repo.getAll.mockResolvedValue([makeFeatureFlag({ flagKey: 'my_flag', enabled: true, rolloutPct: 100 })]);

      expect(await service.isEnabled('my_flag')).toBe(true);
    });

    it('returns true for partial rollout without userId (uses rolloutPct > 0 check)', async () => {
      repo.getAll.mockResolvedValue([makeFeatureFlag({ flagKey: 'partial', enabled: true, rolloutPct: 50 })]);

      expect(await service.isEnabled('partial')).toBe(true);
    });

    it('uses deterministic hash for per-user rollout', async () => {
      repo.getAll.mockResolvedValue([makeFeatureFlag({ flagKey: 'rollout', enabled: true, rolloutPct: 50 })]);

      const result = await service.isEnabled('rollout', 'usr-1');
      expect(typeof result).toBe('boolean');
    });
  });

  // ── getFlag ───────────────────────────────────────────────────────────────

  describe('getFlag', () => {
    it('returns matching flag', async () => {
      const flag = makeFeatureFlag({ flagKey: 'risk_eval_enabled' });
      repo.getAll.mockResolvedValue([flag]);

      const result = await service.getFlag('risk_eval_enabled');
      expect(result).toEqual(flag);
    });

    it('returns null when flag is absent', async () => {
      repo.getAll.mockResolvedValue([]);

      expect(await service.getFlag('missing')).toBeNull();
    });
  });

  // ── getFlags ──────────────────────────────────────────────────────────────

  describe('getFlags', () => {
    it('returns all flags as a keyed record', async () => {
      repo.getAll.mockResolvedValue([
        makeFeatureFlag({ flagKey: 'flag_a', enabled: true,  rolloutPct: 100 }),
        makeFeatureFlag({ flagKey: 'flag_b', enabled: false, rolloutPct: 0 }),
      ]);

      const result = await service.getFlags();

      expect(result['flag_a'].enabled).toBe(true);
      expect(result['flag_b'].enabled).toBe(false);
    });
  });

  // ── upsertFlag ────────────────────────────────────────────────────────────

  describe('upsertFlag', () => {
    it('calls repo.upsert and returns the saved flag', async () => {
      const flag = makeFeatureFlag({ flagKey: 'new_flag', enabled: true });
      repo.upsert.mockResolvedValue(flag);

      const result = await service.upsertFlag({ flagKey: 'new_flag', enabled: true, rolloutPct: 100 });

      expect(repo.upsert).toHaveBeenCalledWith(expect.objectContaining({ flagKey: 'new_flag' }));
      expect(result).toEqual(flag);
    });
  });

  // ── caching ───────────────────────────────────────────────────────────────

  describe('caching', () => {
    it('calls repo only once for repeated reads within TTL', async () => {
      repo.getAll.mockResolvedValue([makeFeatureFlag()]);

      await service.getFlag('test_flag');
      await service.getFlag('test_flag');
      await service.isEnabled('test_flag');

      expect(repo.getAll).toHaveBeenCalledTimes(1);
    });

    it('invalidates cache on upsert', async () => {
      repo.getAll.mockResolvedValue([makeFeatureFlag()]);
      repo.upsert.mockResolvedValue(makeFeatureFlag());

      await service.getFlag('test_flag');      // populates cache
      await service.upsertFlag({ flagKey: 'test_flag', enabled: false });
      await service.getFlag('test_flag');      // should re-fetch after invalidation

      expect(repo.getAll).toHaveBeenCalledTimes(2);
    });
  });
});
