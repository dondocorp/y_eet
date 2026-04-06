import { ConfigRepository } from '../repositories/ConfigRepository';
import { FeatureFlag } from '../types';

const CACHE_TTL_MS = 30_000;

interface CacheEntry { value: FeatureFlag[]; expiresAt: number }

export class ConfigService {
  private repo: ConfigRepository;
  private cache: CacheEntry | null = null;

  constructor() {
    this.repo = new ConfigRepository();
  }

  async getFlags(): Promise<Record<string, { enabled: boolean; rollout_pct: number; variant?: string }>> {
    const flags = await this.getAllCached();
    const result: Record<string, { enabled: boolean; rollout_pct: number; variant?: string }> = {};
    for (const flag of flags) {
      result[flag.flagKey] = {
        enabled: flag.enabled,
        rollout_pct: flag.rolloutPct,
        variant: flag.variant,
      };
    }
    return result;
  }

  async getFlag(key: string): Promise<FeatureFlag | null> {
    const flags = await this.getAllCached();
    return flags.find((f) => f.flagKey === key) ?? null;
  }

  async isEnabled(key: string, userId?: string): Promise<boolean> {
    const flag = await this.getFlag(key);
    if (!flag) return false;
    if (!flag.enabled) return false;
    if (flag.rolloutPct >= 100) return true;
    if (!userId) return flag.rolloutPct > 0;

    // Deterministic rollout based on user ID hash
    const hash = Array.from(userId).reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return (hash % 100) < flag.rolloutPct;
  }

  async upsertFlag(data: {
    flagKey: string;
    enabled: boolean;
    rolloutPct?: number;
    variant?: string;
  }): Promise<FeatureFlag> {
    this.cache = null; // invalidate cache on write
    return this.repo.upsert(data);
  }

  private async getAllCached(): Promise<FeatureFlag[]> {
    if (this.cache && Date.now() < this.cache.expiresAt) {
      return this.cache.value;
    }
    const flags = await this.repo.getAll();
    this.cache = { value: flags, expiresAt: Date.now() + CACHE_TTL_MS };
    return flags;
  }
}
