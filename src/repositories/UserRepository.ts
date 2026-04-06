import { Pool, PoolClient } from 'pg';
import { pool } from '../db/pool';
import { User, UserLimits } from '../types';

function mapUser(row: Record<string, unknown>): User {
  return {
    userId: row.user_id as string,
    email: row.email as string,
    username: row.username as string,
    passwordHash: row.password_hash as string,
    status: row.status as User['status'],
    kycStatus: row.kyc_status as User['kycStatus'],
    jurisdiction: row.jurisdiction as string,
    roles: row.roles as string[],
    createdAt: row.created_at as Date,
    updatedAt: row.updated_at as Date,
  };
}

function mapLimits(row: Record<string, unknown>): UserLimits {
  return {
    userId: row.user_id as string,
    depositLimitDaily: row.deposit_limit_daily as string | undefined,
    depositLimitWeekly: row.deposit_limit_weekly as string | undefined,
    lossLimitDaily: row.loss_limit_daily as string | undefined,
    sessionLimitMinutes: row.session_limit_minutes as number | undefined,
    selfExclusionUntil: row.self_exclusion_until as Date | undefined,
    coolingOffUntil: row.cooling_off_until as Date | undefined,
  };
}

export class UserRepository {
  private db: Pool;

  constructor(db: Pool = pool) {
    this.db = db;
  }

  async findById(userId: string, client?: PoolClient): Promise<User | null> {
    const q = client ?? this.db;
    const result = await q.query('SELECT * FROM users WHERE user_id = $1', [userId]);
    return result.rows[0] ? mapUser(result.rows[0]) : null;
  }

  async findByEmail(email: string): Promise<User | null> {
    const result = await this.db.query('SELECT * FROM users WHERE email = $1', [email]);
    return result.rows[0] ? mapUser(result.rows[0]) : null;
  }

  async create(data: {
    email: string;
    username: string;
    passwordHash: string;
    jurisdiction?: string;
  }): Promise<User> {
    const result = await this.db.query(
      `INSERT INTO users (email, username, password_hash, jurisdiction)
       VALUES ($1, $2, $3, $4)
       RETURNING *`,
      [data.email, data.username, data.passwordHash, data.jurisdiction ?? 'MT'],
    );
    return mapUser(result.rows[0]);
  }

  async updateStatus(userId: string, status: User['status']): Promise<void> {
    await this.db.query(
      'UPDATE users SET status = $1, updated_at = NOW() WHERE user_id = $2',
      [status, userId],
    );
  }

  async getLimits(userId: string): Promise<UserLimits | null> {
    const result = await this.db.query('SELECT * FROM user_limits WHERE user_id = $1', [userId]);
    return result.rows[0] ? mapLimits(result.rows[0]) : null;
  }

  async upsertLimits(userId: string, limits: Partial<UserLimits>): Promise<void> {
    await this.db.query(
      `INSERT INTO user_limits (user_id, deposit_limit_daily, deposit_limit_weekly, loss_limit_daily, session_limit_minutes)
       VALUES ($1, $2, $3, $4, $5)
       ON CONFLICT (user_id) DO UPDATE SET
         deposit_limit_daily  = COALESCE(EXCLUDED.deposit_limit_daily, user_limits.deposit_limit_daily),
         deposit_limit_weekly = COALESCE(EXCLUDED.deposit_limit_weekly, user_limits.deposit_limit_weekly),
         loss_limit_daily     = COALESCE(EXCLUDED.loss_limit_daily, user_limits.loss_limit_daily),
         session_limit_minutes = COALESCE(EXCLUDED.session_limit_minutes, user_limits.session_limit_minutes),
         updated_at = NOW()`,
      [
        userId,
        limits.depositLimitDaily,
        limits.depositLimitWeekly,
        limits.lossLimitDaily,
        limits.sessionLimitMinutes,
      ],
    );
  }
}
