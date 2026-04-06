import { pool } from '../db/pool';
import { FeatureFlag } from '../types';

function mapFlag(row: Record<string, unknown>): FeatureFlag {
  return {
    flagKey: row.flag_key as string,
    enabled: row.enabled as boolean,
    rolloutPct: row.rollout_pct as number,
    variant: row.variant as string | undefined,
    metadata: row.metadata as Record<string, unknown> | undefined,
    createdAt: row.created_at as Date,
    updatedAt: row.updated_at as Date,
  };
}

export class ConfigRepository {
  async getAll(): Promise<FeatureFlag[]> {
    const result = await pool.query<Record<string, unknown>>(
      'SELECT * FROM feature_flags ORDER BY flag_key',
    );
    return result.rows.map(mapFlag);
  }

  async getByKey(key: string): Promise<FeatureFlag | null> {
    const result = await pool.query<Record<string, unknown>>(
      'SELECT * FROM feature_flags WHERE flag_key = $1',
      [key],
    );
    return result.rows[0] ? mapFlag(result.rows[0]) : null;
  }

  async upsert(data: {
    flagKey: string;
    enabled: boolean;
    rolloutPct?: number;
    variant?: string;
    metadata?: Record<string, unknown>;
  }): Promise<FeatureFlag> {
    const result = await pool.query<Record<string, unknown>>(
      `INSERT INTO feature_flags (flag_key, enabled, rollout_pct, variant, metadata)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (flag_key) DO UPDATE SET
         enabled = EXCLUDED.enabled,
         rollout_pct = EXCLUDED.rollout_pct,
         variant = EXCLUDED.variant,
         metadata = EXCLUDED.metadata,
         updated_at = NOW()
       RETURNING *`,
      [
        data.flagKey,
        data.enabled,
        data.rolloutPct ?? 100,
        data.variant ?? null,
        data.metadata ? JSON.stringify(data.metadata) : null,
      ],
    );
    return mapFlag(result.rows[0]);
  }
}
