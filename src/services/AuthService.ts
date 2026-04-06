import bcrypt from 'bcryptjs';
import { FastifyInstance } from 'fastify';
import { v4 as uuidv4 } from 'uuid';
import { UserRepository } from '../repositories/UserRepository';
import { WalletRepository } from '../repositories/WalletRepository';
import { RiskRepository } from '../repositories/RiskRepository';
import { pool } from '../db/pool';
import { config } from '../config';
import { UnauthorizedError, UserSuspendedError } from '../errors';
import { authTokensIssued, authFailures } from '../telemetry/metrics';
import { User } from '../types';

export interface TokenPair {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  sessionId: string;
}

export class AuthService {
  private userRepo: UserRepository;
  private walletRepo: WalletRepository;
  private riskRepo: RiskRepository;
  private fastify?: FastifyInstance;

  constructor(fastify?: FastifyInstance) {
    this.userRepo = new UserRepository();
    this.walletRepo = new WalletRepository();
    this.riskRepo = new RiskRepository();
    this.fastify = fastify;
  }

  setFastify(fastify: FastifyInstance): void {
    this.fastify = fastify;
  }

  async login(
    email: string,
    password: string,
    deviceFingerprint?: string,
  ): Promise<TokenPair> {
    const user = await this.userRepo.findByEmail(email);
    if (!user) {
      authFailures.add(1, { reason: 'user_not_found' });
      throw new UnauthorizedError('Invalid credentials');
    }

    const passwordValid = await bcrypt.compare(password, user.passwordHash);
    if (!passwordValid) {
      authFailures.add(1, { reason: 'bad_password' });
      throw new UnauthorizedError('Invalid credentials');
    }

    if (user.status !== 'active') {
      authFailures.add(1, { reason: `account_${user.status}` });
      throw new UserSuspendedError();
    }

    return this.issueTokens(user, deviceFingerprint);
  }

  async register(data: {
    email: string;
    username: string;
    password: string;
    jurisdiction?: string;
  }): Promise<{ user: User; tokens: TokenPair }> {
    const passwordHash = await bcrypt.hash(data.password, config.BCRYPT_ROUNDS);

    const client = await pool.connect();
    try {
      await client.query('BEGIN');

      const user = await this.userRepo.create({
        email: data.email,
        username: data.username,
        passwordHash,
        jurisdiction: data.jurisdiction,
      });

      // Provision wallet
      await this.walletRepo.create(user.userId);

      // Provision risk profile
      await this.riskRepo.upsertProfile({
        userId: user.userId,
        riskScore: 0,
        riskTier: 'standard',
        flags: [],
      });

      await client.query('COMMIT');

      const tokens = await this.issueTokens(user);
      return { user, tokens };
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  async refresh(refreshToken: string): Promise<TokenPair> {
    if (!this.fastify) throw new Error('FastifyInstance not set');

    // Decode (don't verify — we verify via DB lookup)
    let payload: { sub: string; sessionId: string } | null = null;
    try {
      payload = this.fastify.jwt.decode<{ sub: string; sessionId: string }>(refreshToken);
    } catch {
      throw new UnauthorizedError('Invalid refresh token');
    }

    if (!payload) throw new UnauthorizedError('Invalid refresh token');

    // Look up session
    const client = await pool.connect();
    try {
      await client.query('BEGIN');

      const result = await client.query<{
        session_id: string;
        user_id: string;
        refresh_token_hash: string;
        used_at: Date | null;
        revoked_at: Date | null;
        expires_at: Date;
      }>(
        'SELECT * FROM sessions WHERE session_id = $1 AND user_id = $2 FOR UPDATE',
        [payload.sessionId, payload.sub],
      );

      const session = result.rows[0];
      if (!session) throw new UnauthorizedError('Session not found');
      if (session.revoked_at) throw new UnauthorizedError('Session revoked');
      if (session.used_at) throw new UnauthorizedError('Refresh token already used');
      if (new Date() > session.expires_at) throw new UnauthorizedError('Session expired');

      // Verify token hash
      const tokenValid = await bcrypt.compare(refreshToken, session.refresh_token_hash);
      if (!tokenValid) throw new UnauthorizedError('Invalid refresh token');

      // Mark old session used (single-use rotation)
      await client.query('UPDATE sessions SET used_at = NOW() WHERE session_id = $1', [
        session.session_id,
      ]);

      await client.query('COMMIT');

      const user = await this.userRepo.findById(session.user_id);
      if (!user) throw new UnauthorizedError('User not found');

      return this.issueTokens(user);
    } catch (err) {
      await client.query('ROLLBACK');
      throw err;
    } finally {
      client.release();
    }
  }

  async revoke(sessionId: string, userId: string): Promise<void> {
    await pool.query(
      'UPDATE sessions SET revoked_at = NOW() WHERE session_id = $1 AND user_id = $2',
      [sessionId, userId],
    );
  }

  async validateSession(token: string): Promise<{
    valid: boolean;
    userId: string;
    sessionId: string;
    roles: string[];
    riskTier: string;
  }> {
    if (!this.fastify) throw new Error('FastifyInstance not set');

    try {
      const payload = this.fastify.jwt.verify<{
        sub: string;
        sessionId: string;
        roles: string[];
        riskTier: string;
      }>(token);

      // Check session is not revoked
      const result = await pool.query<{ revoked_at: Date | null }>(
        'SELECT revoked_at FROM sessions WHERE session_id = $1 AND user_id = $2',
        [payload.sessionId, payload.sub],
      );

      if (!result.rows[0] || result.rows[0].revoked_at) {
        return { valid: false, userId: payload.sub, sessionId: payload.sessionId, roles: [], riskTier: 'unknown' };
      }

      return {
        valid: true,
        userId: payload.sub,
        sessionId: payload.sessionId,
        roles: payload.roles,
        riskTier: payload.riskTier,
      };
    } catch {
      return { valid: false, userId: '', sessionId: '', roles: [], riskTier: 'unknown' };
    }
  }

  private async issueTokens(user: User, deviceFingerprint?: string): Promise<TokenPair> {
    if (!this.fastify) throw new Error('FastifyInstance not set');

    const sessionId = uuidv4();
    const riskProfile = await this.riskRepo.getProfile(user.userId);
    const expiresIn = 900; // 15 minutes

    const accessToken = this.fastify.jwt.sign(
      {
        sub: user.userId,
        sessionId,
        roles: user.roles,
        riskTier: riskProfile?.riskTier ?? 'standard',
      },
      { expiresIn },
    );

    const refreshToken = this.fastify.jwt.sign(
      { sub: user.userId, sessionId, type: 'refresh' },
      { expiresIn: `${config.REFRESH_TOKEN_EXPIRY_DAYS}d` },
    );

    const refreshTokenHash = await bcrypt.hash(refreshToken, 10);
    const expiresAt = new Date();
    expiresAt.setDate(expiresAt.getDate() + config.REFRESH_TOKEN_EXPIRY_DAYS);

    await pool.query(
      `INSERT INTO sessions (session_id, user_id, refresh_token_hash, device_fingerprint, expires_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [sessionId, user.userId, refreshTokenHash, deviceFingerprint ?? null, expiresAt],
    );

    authTokensIssued.add(1, { type: 'access' });

    return { accessToken, refreshToken, expiresIn, sessionId };
  }
}
