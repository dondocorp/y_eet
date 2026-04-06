import { Pool, PoolClient } from 'pg';
import { pool } from '../db/pool';
import { GameSession, SessionStatus } from '../types';

function mapSession(row: Record<string, unknown>): GameSession {
  return {
    sessionId: row.session_id as string,
    userId: row.user_id as string,
    gameId: row.game_id as string,
    status: row.status as SessionStatus,
    clientSeed: row.client_seed as string | undefined,
    serverSeed: row.server_seed as string | undefined,
    serverSeedHash: row.server_seed_hash as string,
    startedAt: row.started_at as Date,
    lastHeartbeatAt: row.last_heartbeat_at as Date,
    closedAt: row.closed_at as Date | undefined,
    expiresAt: row.expires_at as Date,
  };
}

export class GameSessionRepository {
  private db: Pool;

  constructor(db: Pool = pool) {
    this.db = db;
  }

  async findById(sessionId: string, client?: PoolClient): Promise<GameSession | null> {
    const q = client ?? this.db;
    const result = await q.query<Record<string, unknown>>(
      'SELECT * FROM game_sessions WHERE session_id = $1',
      [sessionId],
    );
    return result.rows[0] ? mapSession(result.rows[0]) : null;
  }

  async findByIdempotencyKey(key: string): Promise<GameSession | null> {
    const result = await this.db.query<Record<string, unknown>>(
      'SELECT * FROM game_sessions WHERE idempotency_key = $1',
      [key],
    );
    return result.rows[0] ? mapSession(result.rows[0]) : null;
  }

  async create(data: {
    userId: string;
    gameId: string;
    clientSeed?: string;
    serverSeed: string;
    serverSeedHash: string;
    idempotencyKey?: string;
  }): Promise<GameSession> {
    const result = await this.db.query<Record<string, unknown>>(
      `INSERT INTO game_sessions
         (user_id, game_id, client_seed, server_seed, server_seed_hash, idempotency_key)
       VALUES ($1,$2,$3,$4,$5,$6)
       RETURNING *`,
      [
        data.userId,
        data.gameId,
        data.clientSeed ?? null,
        data.serverSeed,
        data.serverSeedHash,
        data.idempotencyKey ?? null,
      ],
    );
    return mapSession(result.rows[0]);
  }

  async heartbeat(sessionId: string): Promise<GameSession | null> {
    const result = await this.db.query<Record<string, unknown>>(
      `UPDATE game_sessions
       SET last_heartbeat_at = NOW(), expires_at = NOW() + INTERVAL '30 minutes'
       WHERE session_id = $1 AND status = 'active'
       RETURNING *`,
      [sessionId],
    );
    return result.rows[0] ? mapSession(result.rows[0]) : null;
  }

  async close(sessionId: string, userId: string): Promise<GameSession | null> {
    const result = await this.db.query<Record<string, unknown>>(
      `UPDATE game_sessions
       SET status = 'closed', closed_at = NOW()
       WHERE session_id = $1 AND user_id = $2 AND status = 'active'
       RETURNING *`,
      [sessionId, userId],
    );
    return result.rows[0] ? mapSession(result.rows[0]) : null;
  }

  async expireStale(): Promise<number> {
    const result = await this.db.query(
      `UPDATE game_sessions SET status = 'expired'
       WHERE status = 'active' AND expires_at < NOW()`,
    );
    return result.rowCount ?? 0;
  }

  async countActive(): Promise<number> {
    const result = await this.db.query<{ count: string }>(
      "SELECT COUNT(*) as count FROM game_sessions WHERE status = 'active'",
    );
    return parseInt(result.rows[0].count, 10);
  }
}
