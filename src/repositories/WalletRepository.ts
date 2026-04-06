import { Pool, PoolClient } from 'pg';
import { pool, withTransaction } from '../db/pool';
import { WalletAccount, WalletTransaction, TxType } from '../types';
import { InsufficientFundsError, WalletNotFoundError } from '../errors';
import { walletTransfersTotal, walletIdempotencyHits, walletTransferDuration } from '../telemetry/metrics';

function mapAccount(row: Record<string, unknown>): WalletAccount {
  return {
    walletId: row.wallet_id as string,
    userId: row.user_id as string,
    currency: row.currency as string,
    balance: String(row.balance),
    reserved: String(row.reserved),
    createdAt: row.created_at as Date,
    updatedAt: row.updated_at as Date,
  };
}

function mapTx(row: Record<string, unknown>): WalletTransaction {
  return {
    txId: row.tx_id as string,
    walletId: row.wallet_id as string,
    userId: row.user_id as string,
    type: row.type as TxType,
    amount: String(row.amount),
    balanceAfter: String(row.balance_after),
    referenceId: row.reference_id as string | undefined,
    idempotencyKey: row.idempotency_key as string,
    metadata: row.metadata as Record<string, unknown> | undefined,
    createdAt: row.created_at as Date,
  };
}

export class WalletRepository {
  private db: Pool;

  constructor(db: Pool = pool) {
    this.db = db;
  }

  async getByUserId(userId: string, client?: PoolClient): Promise<WalletAccount | null> {
    const q = client ?? this.db;
    const result = await q.query('SELECT * FROM wallet_accounts WHERE user_id = $1', [userId]);
    return result.rows[0] ? mapAccount(result.rows[0]) : null;
  }

  async create(userId: string, currency = 'USD'): Promise<WalletAccount> {
    const result = await this.db.query(
      'INSERT INTO wallet_accounts (user_id, currency) VALUES ($1, $2) RETURNING *',
      [userId, currency],
    );
    return mapAccount(result.rows[0]);
  }

  /**
   * Atomically debit the wallet (bet reserve or withdrawal).
   * Uses SERIALIZABLE isolation + row-level lock to prevent double-spend.
   * Returns existing tx if idempotency key already exists.
   */
  async debit(params: {
    userId: string;
    amount: string;
    type: TxType;
    referenceId: string;
    idempotencyKey: string;
    metadata?: Record<string, unknown>;
  }): Promise<WalletTransaction> {
    const start = Date.now();
    return withTransaction(async (client) => {
      // Check idempotency first (before locking)
      const existing = await client.query<Record<string, unknown>>(
        'SELECT * FROM wallet_transactions WHERE idempotency_key = $1',
        [params.idempotencyKey],
      );
      if (existing.rows[0]) {
        walletIdempotencyHits.add(1, { type: params.type });
        return mapTx(existing.rows[0]);
      }

      // Lock wallet row
      const walletResult = await client.query<Record<string, unknown>>(
        'SELECT * FROM wallet_accounts WHERE user_id = $1 FOR UPDATE',
        [params.userId],
      );
      if (!walletResult.rows[0]) throw new WalletNotFoundError(params.userId);

      const wallet = mapAccount(walletResult.rows[0]);
      const available = parseFloat(wallet.balance);
      const amount = parseFloat(params.amount);

      if (available < amount) {
        throw new InsufficientFundsError(wallet.balance, params.amount);
      }

      const newBalance = (available - amount).toFixed(2);
      const newReserved =
        params.type === 'bet_reserve'
          ? (parseFloat(wallet.reserved) + amount).toFixed(2)
          : wallet.reserved;

      // Insert immutable transaction record
      const txResult = await client.query<Record<string, unknown>>(
        `INSERT INTO wallet_transactions
           (wallet_id, user_id, type, amount, balance_after, reference_id, idempotency_key, metadata)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
         RETURNING *`,
        [
          wallet.walletId,
          params.userId,
          params.type,
          `-${params.amount}`,
          newBalance,
          params.referenceId,
          params.idempotencyKey,
          params.metadata ? JSON.stringify(params.metadata) : null,
        ],
      );

      // Update running balance
      await client.query(
        'UPDATE wallet_accounts SET balance = $1, reserved = $2, updated_at = NOW() WHERE wallet_id = $3',
        [newBalance, newReserved, wallet.walletId],
      );

      walletTransfersTotal.add(1, { type: params.type, status: 'success' });
      walletTransferDuration.record(Date.now() - start, { type: params.type });
      return mapTx(txResult.rows[0]);
    }, 'SERIALIZABLE');
  }

  /**
   * Atomically credit the wallet (win payout or deposit).
   * Also handles releasing reserved funds.
   */
  async credit(params: {
    userId: string;
    amount: string;
    type: TxType;
    referenceId: string;
    idempotencyKey: string;
    releaseReserved?: string;
    metadata?: Record<string, unknown>;
  }): Promise<WalletTransaction> {
    const start = Date.now();
    return withTransaction(async (client) => {
      const existing = await client.query<Record<string, unknown>>(
        'SELECT * FROM wallet_transactions WHERE idempotency_key = $1',
        [params.idempotencyKey],
      );
      if (existing.rows[0]) {
        walletIdempotencyHits.add(1, { type: params.type });
        return mapTx(existing.rows[0]);
      }

      const walletResult = await client.query<Record<string, unknown>>(
        'SELECT * FROM wallet_accounts WHERE user_id = $1 FOR UPDATE',
        [params.userId],
      );
      if (!walletResult.rows[0]) throw new WalletNotFoundError(params.userId);

      const wallet = mapAccount(walletResult.rows[0]);
      const creditAmount = parseFloat(params.amount);
      const newBalance = (parseFloat(wallet.balance) + creditAmount).toFixed(2);
      const releaseAmount = parseFloat(params.releaseReserved ?? '0');
      const newReserved = Math.max(0, parseFloat(wallet.reserved) - releaseAmount).toFixed(2);

      const txResult = await client.query<Record<string, unknown>>(
        `INSERT INTO wallet_transactions
           (wallet_id, user_id, type, amount, balance_after, reference_id, idempotency_key, metadata)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
         RETURNING *`,
        [
          wallet.walletId,
          params.userId,
          params.type,
          params.amount,
          newBalance,
          params.referenceId,
          params.idempotencyKey,
          params.metadata ? JSON.stringify(params.metadata) : null,
        ],
      );

      await client.query(
        'UPDATE wallet_accounts SET balance = $1, reserved = $2, updated_at = NOW() WHERE wallet_id = $3',
        [newBalance, newReserved, wallet.walletId],
      );

      walletTransfersTotal.add(1, { type: params.type, status: 'success' });
      walletTransferDuration.record(Date.now() - start, { type: params.type });
      return mapTx(txResult.rows[0]);
    }, 'SERIALIZABLE');
  }

  async getTransactions(
    userId: string,
    opts: { limit?: number; cursor?: string; type?: string } = {},
  ): Promise<{ transactions: WalletTransaction[]; nextCursor: string | null }> {
    const limit = Math.min(opts.limit ?? 20, 100);
    const params: unknown[] = [userId, limit + 1];
    let cursorClause = '';

    if (opts.cursor) {
      const cursorDate = Buffer.from(opts.cursor, 'base64').toString('utf-8');
      cursorClause = `AND created_at < $${params.length + 1}`;
      params.push(cursorDate);
    }

    const typeClause = opts.type ? `AND type = $${params.length + 1}` : '';
    if (opts.type) params.push(opts.type);

    const result = await this.db.query<Record<string, unknown>>(
      `SELECT * FROM wallet_transactions
       WHERE user_id = $1 ${cursorClause} ${typeClause}
       ORDER BY created_at DESC
       LIMIT $2`,
      params,
    );

    const rows = result.rows;
    const hasMore = rows.length > limit;
    const transactions = rows.slice(0, limit).map(mapTx);
    const nextCursor =
      hasMore && transactions.length > 0
        ? Buffer.from(transactions[transactions.length - 1].createdAt.toISOString()).toString('base64')
        : null;

    return { transactions, nextCursor };
  }
}
