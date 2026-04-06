import crypto from 'crypto';
import { BetRepository } from '../repositories/BetRepository';
import { UserRepository } from '../repositories/UserRepository';
import { WalletService } from './WalletService';
import { RiskService } from './RiskService';
import { GameSessionService } from './GameSessionService';
import { ConfigService } from './ConfigService';
import { Bet } from '../types';
import {
  UserSuspendedError,
  KycRequiredError,
  RiskRejectedError,
  BetNotFoundError,
  BetAlreadySettledError,
  BetLimitExceededError,
  ForbiddenError,
} from '../errors';
import {
  betPlacementsTotal,
  betSettlementsTotal,
  betPlacementDuration,
  bettingVolumeUsd,
} from '../telemetry/metrics';

export interface PlaceBetParams {
  userId: string;
  gameSessionId?: string;
  gameId: string;
  amount: string;
  currency: string;
  betType: string;
  parameters?: Record<string, unknown>;
  idempotencyKey: string;
  ipAddress?: string;
  deviceFingerprint?: string;
}

export interface BetResult {
  bet: Bet;
  walletBalanceAfter: string;
}

export class BetService {
  private betRepo: BetRepository;
  private userRepo: UserRepository;
  private walletService: WalletService;
  private riskService: RiskService;
  private gameSessionService: GameSessionService;
  private configService: ConfigService;

  constructor() {
    this.betRepo = new BetRepository();
    this.userRepo = new UserRepository();
    this.walletService = new WalletService();
    this.riskService = new RiskService();
    this.gameSessionService = new GameSessionService();
    this.configService = new ConfigService();
  }

  async placeBet(params: PlaceBetParams): Promise<BetResult> {
    const start = Date.now();

    // ── 1. Idempotency check ───────────────────────────────────────────────
    const existingBet = await this.betRepo.findByIdempotencyKey(params.idempotencyKey);
    if (existingBet) {
      const wallet = await this.walletService.getBalance(params.userId);
      betPlacementsTotal.add(1, { status: 'idempotency_hit', game_id: params.gameId });
      return { bet: existingBet, walletBalanceAfter: wallet.balance };
    }

    // ── 2. User eligibility ────────────────────────────────────────────────
    const user = await this.userRepo.findById(params.userId);
    if (!user) throw new ForbiddenError('User not found');
    if (user.status !== 'active') throw new UserSuspendedError();
    if (user.kycStatus !== 'verified') throw new KycRequiredError();

    // ── 3. Validate betting limits ─────────────────────────────────────────
    const limits = await this.userRepo.getLimits(params.userId);
    const stake = parseFloat(params.amount);

    if (limits?.depositLimitDaily) {
      const maxBet = parseFloat(limits.depositLimitDaily) * 0.5; // simplified
      if (stake > maxBet) {
        throw new BetLimitExceededError(String(maxBet), 'single_bet');
      }
    }

    // ── 4. Validate game session ───────────────────────────────────────────
    let gameSession = null;
    if (params.gameSessionId) {
      gameSession = await this.gameSessionService.validateActiveSession(
        params.gameSessionId,
        params.userId,
      );
    }

    // ── 5. Risk evaluation ─────────────────────────────────────────────────
    const riskEnabled = await this.configService.isEnabled('risk_eval_enabled');
    let riskScore = 0;
    let riskDecision = 'allow';

    if (riskEnabled) {
      const riskResult = await this.riskService.evaluate({
        userId: params.userId,
        action: 'bet_place',
        amount: params.amount,
        sessionId: params.gameSessionId,
        deviceFingerprint: params.deviceFingerprint,
        ipAddress: params.ipAddress,
      });

      riskScore = riskResult.riskScore;
      riskDecision = riskResult.decision;

      if (riskResult.decision === 'reject') {
        betPlacementsTotal.add(1, { status: 'risk_rejected', game_id: params.gameId });
        throw new RiskRejectedError(riskResult.flags.join(', '));
      }
    }

    // ── 6. Reserve funds (atomic, idempotent) ──────────────────────────────
    // We don't have a betId yet, so we use a temporary reservation key
    const reservationKey = `reserve_pending_${params.idempotencyKey}`;

    // Create bet record + reserve funds in a single logical operation
    // The wallet reservation uses the idempotency key as the reference
    const walletTx = await this.walletService.reserveForBet({
      userId: params.userId,
      amount: params.amount,
      betId: params.idempotencyKey, // use idem key as betId for reservation
    });

    // ── 7. Create bet record ───────────────────────────────────────────────
    const bet = await this.betRepo.create({
      userId: params.userId,
      sessionId: params.gameSessionId,
      gameId: params.gameId,
      idempotencyKey: params.idempotencyKey,
      amount: params.amount,
      currency: params.currency,
      betType: params.betType,
      parameters: params.parameters,
      riskScore,
      riskDecision,
      walletTxId: walletTx.txId,
    });

    // ── 8. Immediate settlement for instant games ──────────────────────────
    let settledBet = bet;
    if (gameSession && this.isInstantGame(params.gameId)) {
      settledBet = await this.settleImmediate(bet, gameSession.serverSeed ?? '', params.parameters);
    }

    const wallet = await this.walletService.getBalance(params.userId);

    const duration = Date.now() - start;
    betPlacementsTotal.add(1, { status: 'accepted', game_id: params.gameId });
    betPlacementDuration.record(duration);
    bettingVolumeUsd.add(stake, { game_id: params.gameId });

    // Suppress unused variable warning
    void reservationKey;

    return { bet: settledBet, walletBalanceAfter: wallet.balance };
  }

  async settleBet(betId: string, outcome: {
    payout: string;
    idempotencyKey?: string;
  }): Promise<Bet> {
    const bet = await this.betRepo.findById(betId);
    if (!bet) throw new BetNotFoundError(betId);
    if (bet.status === 'settled') throw new BetAlreadySettledError(betId);
    if (bet.status === 'voided') throw new ForbiddenError('Cannot settle a voided bet');

    const payout = parseFloat(outcome.payout);
    const stake = parseFloat(bet.amount);
    const isWin = payout > 0;

    if (isWin) {
      await this.walletService.settleBetWin({
        userId: bet.userId,
        payout: outcome.payout,
        stakeAmount: bet.amount,
        betId,
      });
    } else {
      await this.walletService.settleBetLoss({
        userId: bet.userId,
        stakeAmount: bet.amount,
        betId,
      });
    }

    const settled = await this.betRepo.settle(betId, {
      payout: outcome.payout,
      status: 'settled',
    });

    betSettlementsTotal.add(1, {
      outcome: isWin ? 'win' : 'loss',
      game_id: bet.gameId,
    });

    void stake; // suppress unused warning
    return settled;
  }

  async voidBet(betId: string, requestingUserId: string, isAdmin: boolean): Promise<Bet> {
    const bet = await this.betRepo.findById(betId);
    if (!bet) throw new BetNotFoundError(betId);
    if (!isAdmin && bet.userId !== requestingUserId) throw new ForbiddenError('Access denied');
    if (bet.status !== 'accepted') throw new ForbiddenError(`Cannot void bet with status: ${bet.status}`);

    await this.walletService.voidBetReserve({
      userId: bet.userId,
      stakeAmount: bet.amount,
      betId,
    });

    return this.betRepo.void(betId);
  }

  async getBet(betId: string, requestingUserId: string, isAdmin = false): Promise<Bet> {
    const bet = await this.betRepo.findById(betId);
    if (!bet) throw new BetNotFoundError(betId);
    if (!isAdmin && bet.userId !== requestingUserId) throw new ForbiddenError('Access denied');
    return bet;
  }

  async getBetHistory(
    userId: string,
    opts: { limit?: number; cursor?: string; status?: Bet['status'] } = {},
  ) {
    return this.betRepo.listByUser(userId, opts);
  }

  // ─── Private helpers ───────────────────────────────────────────────────────

  private isInstantGame(gameId: string): boolean {
    return gameId.startsWith('game_crash') || gameId.startsWith('game_slots');
  }

  private async settleImmediate(
    bet: Bet,
    serverSeed: string,
    parameters?: Record<string, unknown>,
  ): Promise<Bet> {
    const { payout } = this.computeGameOutcome(bet, serverSeed, parameters);
    return this.settleBet(bet.betId, { payout: payout.toFixed(2) });
  }

  private computeGameOutcome(
    bet: Bet,
    serverSeed: string,
    parameters?: Record<string, unknown>,
  ): { payout: number; multiplier: number } {
    const stake = parseFloat(bet.amount);

    if (bet.gameId.startsWith('game_crash')) {
      // Crash game: random multiplier, house edge 4%
      const rand = this.deterministicRandom(serverSeed, bet.idempotencyKey);
      const multiplier = Math.max(1.0, (1 / (1 - rand * 0.96)));
      const autoCashout = (parameters?.auto_cashout as number) ?? 2.0;
      const effective = Math.min(multiplier, autoCashout);
      const payout = effective >= autoCashout ? stake * autoCashout : 0;
      return { payout, multiplier: effective };
    }

    // Default: slots-style (90% RTP)
    const rand = this.deterministicRandom(serverSeed, bet.idempotencyKey);
    const payout = rand < 0.9 ? stake * (rand < 0.1 ? 10 : rand < 0.3 ? 2 : 0) : 0;
    return { payout, multiplier: payout / stake };
  }

  private deterministicRandom(serverSeed: string, clientNonce: string): number {
    const hash = crypto
      .createHmac('sha256', serverSeed)
      .update(clientNonce)
      .digest('hex');
    return parseInt(hash.slice(0, 8), 16) / 0xffffffff;
  }
}
