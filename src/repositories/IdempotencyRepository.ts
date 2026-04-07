import { pool } from '../db/pool';
import { IdempotencyRecord } from '../types';

export class IdempotencyRepository {
  async get(key: string, service: string): Promise<IdempotencyRecord | null> {
    const result = await pool.query<{
      key: string;
      service: string;
      endpoint: string;
      status_code: number;
      response_body: unknown;
      created_at: Date;
      expires_at: Date;
    }>(
      `SELECT * FROM idempotency_keys
       WHERE key = $1 AND service = $2 AND expires_at > NOW()`,
      [key, service],
    );
    if (!result.rows[0]) return null;
    const r = result.rows[0];
    return {
      key: r.key,
      service: r.service,
      endpoint: r.endpoint,
      statusCode: r.status_code,
      responseBody: r.response_body,
      createdAt: r.created_at,
      expiresAt: r.expires_at,
    };
  }

  async set(
    key: string,
    service: string,
    endpoint: string,
    statusCode: number,
    responseBody: unknown,
    ttlHours: number,
  ): Promise<void> {
    await pool.query(
      `INSERT INTO idempotency_keys (key, service, endpoint, status_code, response_body, expires_at)
       VALUES ($1, $2, $3, $4, $5, NOW() + ($6 || ' hours')::INTERVAL)
       ON CONFLICT (key, service) DO NOTHING`,
      [key, service, endpoint, statusCode, JSON.stringify(responseBody), ttlHours],
    );
  }

  async cleanup(): Promise<number> {
    const result = await pool.query('DELETE FROM idempotency_keys WHERE expires_at < NOW()');
    return result.rowCount ?? 0;
  }
}
