import { pool } from '../db/pool';
import { UserRiskProfile, FraudSignal } from '../types';

function mapProfile(row: Record<string, unknown>): UserRiskProfile {
  return {
    userId: row.user_id as string,
    riskScore: row.risk_score as number,
    riskTier: row.risk_tier as UserRiskProfile['riskTier'],
    flags: row.flags as string[],
    lastEvaluatedAt: row.last_evaluated_at as Date,
    updatedAt: row.updated_at as Date,
  };
}

export class RiskRepository {
  async getProfile(userId: string): Promise<UserRiskProfile | null> {
    const result = await pool.query<Record<string, unknown>>(
      'SELECT * FROM user_risk_profiles WHERE user_id = $1',
      [userId],
    );
    return result.rows[0] ? mapProfile(result.rows[0]) : null;
  }

  async upsertProfile(profile: Partial<UserRiskProfile> & { userId: string }): Promise<UserRiskProfile> {
    const result = await pool.query<Record<string, unknown>>(
      `INSERT INTO user_risk_profiles (user_id, risk_score, risk_tier, flags)
       VALUES ($1, $2, $3, $4)
       ON CONFLICT (user_id) DO UPDATE SET
         risk_score = EXCLUDED.risk_score,
         risk_tier = EXCLUDED.risk_tier,
         flags = EXCLUDED.flags,
         last_evaluated_at = NOW(),
         updated_at = NOW()
       RETURNING *`,
      [
        profile.userId,
        profile.riskScore ?? 0,
        profile.riskTier ?? 'standard',
        profile.flags ?? [],
      ],
    );
    return mapProfile(result.rows[0]);
  }

  async ingestSignal(signal: Omit<FraudSignal, 'signalId' | 'createdAt'>): Promise<string> {
    const result = await pool.query<{ signal_id: string }>(
      `INSERT INTO fraud_signals (user_id, signal_type, severity, context, occurred_at)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING signal_id`,
      [
        signal.userId,
        signal.signalType,
        signal.severity,
        signal.context ? JSON.stringify(signal.context) : null,
        signal.occurredAt,
      ],
    );
    return result.rows[0].signal_id;
  }

  async getRecentSignals(userId: string, windowMinutes = 60): Promise<FraudSignal[]> {
    const result = await pool.query<Record<string, unknown>>(
      `SELECT * FROM fraud_signals
       WHERE user_id = $1 AND occurred_at > NOW() - ($2 || ' minutes')::INTERVAL
       ORDER BY occurred_at DESC`,
      [userId, windowMinutes],
    );
    return result.rows.map((r) => ({
      signalId: r.signal_id as string,
      userId: r.user_id as string,
      signalType: r.signal_type as string,
      severity: r.severity as FraudSignal['severity'],
      context: r.context as Record<string, unknown> | undefined,
      occurredAt: r.occurred_at as Date,
      createdAt: r.created_at as Date,
    }));
  }

  async countBetsInWindow(userId: string, windowSeconds = 60): Promise<number> {
    const result = await pool.query<{ count: string }>(
      `SELECT COUNT(*) as count FROM bets
       WHERE user_id = $1 AND placed_at > NOW() - ($2 || ' seconds')::INTERVAL`,
      [userId, windowSeconds],
    );
    return parseInt(result.rows[0].count, 10);
  }

  async sumLossesToday(userId: string): Promise<string> {
    const result = await pool.query<{ total: string | null }>(
      `SELECT COALESCE(SUM(amount), 0) as total FROM bets
       WHERE user_id = $1
         AND status = 'settled'
         AND COALESCE(payout, 0) < amount
         AND placed_at >= CURRENT_DATE`,
      [userId],
    );
    return String(result.rows[0].total ?? '0');
  }
}
