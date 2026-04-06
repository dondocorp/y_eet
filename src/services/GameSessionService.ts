import crypto from 'crypto';
import { GameSessionRepository } from '../repositories/GameSessionRepository';
import { GameSession } from '../types';
import { SessionNotFoundError, SessionExpiredError, ForbiddenError } from '../errors';
import { activeGameSessions } from '../telemetry/metrics';

export class GameSessionService {
  private repo: GameSessionRepository;

  constructor() {
    this.repo = new GameSessionRepository();
    // Observe active sessions every 30s
    setInterval(async () => {
      const count = await this.repo.countActive().catch(() => 0);
      activeGameSessions.addCallback((obs) => obs.observe(count));
    }, 30_000);
  }

  async createSession(params: {
    userId: string;
    gameId: string;
    clientSeed?: string;
    idempotencyKey?: string;
  }): Promise<GameSession> {
    // Idempotency: return existing session if key matches
    if (params.idempotencyKey) {
      const existing = await this.repo.findByIdempotencyKey(params.idempotencyKey);
      if (existing) return existing;
    }

    // Generate provably fair server seed
    const serverSeed = crypto.randomBytes(32).toString('hex');
    const serverSeedHash = crypto
      .createHash('sha256')
      .update(serverSeed)
      .digest('hex');

    return this.repo.create({
      userId: params.userId,
      gameId: params.gameId,
      clientSeed: params.clientSeed,
      serverSeed,
      serverSeedHash,
      idempotencyKey: params.idempotencyKey,
    });
  }

  async getSession(sessionId: string, userId: string): Promise<GameSession> {
    const session = await this.repo.findById(sessionId);
    if (!session) throw new SessionNotFoundError(sessionId);
    if (session.userId !== userId) throw new ForbiddenError('Access denied');
    return session;
  }

  async heartbeat(sessionId: string, userId: string): Promise<GameSession> {
    const session = await this.repo.findById(sessionId);
    if (!session) throw new SessionNotFoundError(sessionId);
    if (session.userId !== userId) throw new ForbiddenError('Access denied');
    if (session.status !== 'active') throw new SessionExpiredError(sessionId);

    const updated = await this.repo.heartbeat(sessionId);
    if (!updated) throw new SessionExpiredError(sessionId);
    return updated;
  }

  async closeSession(sessionId: string, userId: string): Promise<GameSession> {
    const session = await this.repo.findById(sessionId);
    if (!session) throw new SessionNotFoundError(sessionId);
    if (session.userId !== userId) throw new ForbiddenError('Access denied');

    const closed = await this.repo.close(sessionId, userId);
    return closed ?? session; // already closed — idempotent
  }

  async validateActiveSession(sessionId: string, userId: string): Promise<GameSession> {
    const session = await this.repo.findById(sessionId);
    if (!session) throw new SessionNotFoundError(sessionId);
    if (session.userId !== userId) throw new ForbiddenError('Session does not belong to user');
    if (session.status !== 'active') throw new SessionExpiredError(sessionId);
    if (new Date() > session.expiresAt) {
      await this.repo.close(sessionId, userId).catch(() => {/* best-effort */});
      throw new SessionExpiredError(sessionId);
    }
    return session;
  }

  /**
   * Reveal server seed after session closes (provably fair).
   * Only callable on closed sessions.
   */
  async revealServerSeed(sessionId: string, userId: string): Promise<{ serverSeed: string; serverSeedHash: string; clientSeed?: string }> {
    const session = await this.repo.findById(sessionId);
    if (!session) throw new SessionNotFoundError(sessionId);
    if (session.userId !== userId) throw new ForbiddenError('Access denied');
    if (session.status === 'active') throw new ForbiddenError('Session must be closed before seed reveal');
    return {
      serverSeed: session.serverSeed ?? '',
      serverSeedHash: session.serverSeedHash,
      clientSeed: session.clientSeed,
    };
  }

  /**
   * Deterministic game outcome from seeds + nonce.
   * Used by bet placement to compute immediate results.
   */
  computeOutcome(serverSeed: string, clientSeed: string, nonce: string): number {
    const hash = crypto
      .createHmac('sha256', serverSeed)
      .update(`${clientSeed}:${nonce}`)
      .digest('hex');

    // Convert first 8 hex chars to a float between 0 and 1
    const intValue = parseInt(hash.slice(0, 8), 16);
    return intValue / 0xffffffff;
  }
}
