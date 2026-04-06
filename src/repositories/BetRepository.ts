import { Pool, PoolClient } from 'pg';
import { pool } from '../db/pool';
import { Bet, BetStatus } from '../types';

function mapBet(row: Record<string, unknown>): Bet {
  return {
    betId: row.bet_id as string,
    userId: row.user_id as string,
    sessionId: row.session_id as string | undefined,
    gameId: row.game_id as string,
    idempotencyKey: row.idempotency_key as string,
    status: row.status as BetStatus,
    amount: String(row.amount),
    currency: row.currency as string,
    payout: row.payout != null ? String(row.payout) : undefined,
    betType: row.bet_type as string,
    parameters: row.parameters as Record<string, unknown> | undefined,
    riskScore: row.risk_score as number | undefined,
    riskDecision: row.risk_decision as string | undefined,
    walletTxId: row.wallet_tx_id as string | undefined,
    placedAt: row.placed_at as Date,
    settledAt: row.settled_at as Date | undefined,
  };
}

export class BetRepository {
  private db: Pool;

  constructor(db: Pool = pool) {
    this.db = db;
  }

  async findById(betId: string, client?: PoolClient): Promise<Bet | null> {
    const q = client ?? this.db;
    const result = await q.query<Record<string, unknown>>(
      'SELECT * FROM bets WHERE bet_id = $1',
      [betId],
    );
    return result.rows[0] ? mapBet(result.rows[0]) : null;
  }

  async findByIdempotencyKey(key: string, client?: PoolClient): Promise<Bet | null> {
    const q = client ?? this.db;
    const result = await q.query<Record<string, unknown>>(
      'SELECT * FROM bets WHERE idempotency_key = $1',
      [key],
    );
    return result.rows[0] ? mapBet(result.rows[0]) : null;
  }

  async create(
    data: {
      userId: string;
      sessionId?: string;
      gameId: string;
      idempotencyKey: string;
      amount: string;
      currency: string;
      betType: string;
      parameters?: Record<string, unknown>;
      riskScore?: number;
      riskDecision?: string;
      walletTxId?: string;
    },
    client?: PoolClient,
  ): Promise<Bet> {
    const q = client ?? this.db;
    const result = await q.query<Record<string, unknown>>(
      `INSERT INTO bets
         (user_id, session_id, game_id, idempotency_key, amount, currency, bet_type,
          parameters, risk_score, risk_decision, wallet_tx_id)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
       RETURNING *`,
      [
        data.userId,
        data.sessionId ?? null,
        data.gameId,
        data.idempotencyKey,
        data.amount,
        data.currency,
        data.betType,
        data.parameters ? JSON.stringify(data.parameters) : null,
        data.riskScore ?? null,
        data.riskDecision ?? null,
        data.walletTxId ?? null,
      ],
    );
    return mapBet(result.rows[0]);
  }

  async settle(
    betId: string,
    outcome: { payout: string; status: BetStatus },
    client?: PoolClient,
  ): Promise<Bet> {
    const q = client ?? this.db;
    const result = await q.query<Record<string, unknown>>(
      `UPDATE bets
       SET status = $1, payout = $2, settled_at = NOW()
       WHERE bet_id = $3 AND status IN ('accepted','pending_settlement')
       RETURNING *`,
      [outcome.status, outcome.payout, betId],
    );
    if (!result.rows[0]) throw new Error(`Bet ${betId} not found or already settled`);
    return mapBet(result.rows[0]);
  }

  async void(betId: string, client?: PoolClient): Promise<Bet> {
    const q = client ?? this.db;
    const result = await q.query<Record<string, unknown>>(
      `UPDATE bets SET status = 'voided', settled_at = NOW()
       WHERE bet_id = $1 AND status = 'accepted'
       RETURNING *`,
      [betId],
    );
    if (!result.rows[0]) throw new Error(`Bet ${betId} not found or cannot be voided`);
    return mapBet(result.rows[0]);
  }

  async listByUser(
    userId: string,
    opts: { limit?: number; cursor?: string; status?: BetStatus } = {},
  ): Promise<{ bets: Bet[]; nextCursor: string | null }> {
    const limit = Math.min(opts.limit ?? 20, 100);
    const params: unknown[] = [userId, limit + 1];
    let cursorClause = '';

    if (opts.cursor) {
      const cursorDate = Buffer.from(opts.cursor, 'base64').toString('utf-8');
      cursorClause = `AND placed_at < $${params.length + 1}`;
      params.push(cursorDate);
    }

    const statusClause = opts.status ? `AND status = $${params.length + 1}` : '';
    if (opts.status) params.push(opts.status);

    const result = await this.db.query<Record<string, unknown>>(
      `SELECT * FROM bets
       WHERE user_id = $1 ${cursorClause} ${statusClause}
       ORDER BY placed_at DESC
       LIMIT $2`,
      params,
    );

    const rows = result.rows;
    const hasMore = rows.length > limit;
    const bets = rows.slice(0, limit).map(mapBet);
    const nextCursor =
      hasMore && bets.length > 0
        ? Buffer.from(bets[bets.length - 1].placedAt.toISOString()).toString('base64')
        : null;

    return { bets, nextCursor };
  }
}
