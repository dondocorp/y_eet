import { BetService } from '../../../src/services/BetService';
import { BetRepository } from '../../../src/repositories/BetRepository';
import { UserRepository } from '../../../src/repositories/UserRepository';
import { WalletService } from '../../../src/services/WalletService';
import { RiskService } from '../../../src/services/RiskService';
import { GameSessionService } from '../../../src/services/GameSessionService';
import { ConfigService } from '../../../src/services/ConfigService';
import {
  UserSuspendedError,
  KycRequiredError,
  RiskRejectedError,
  BetNotFoundError,
  BetAlreadySettledError,
  ForbiddenError,
  BetLimitExceededError,
} from '../../../src/errors';
import { makeUser, makeBet, makeWallet, makeWalletTx, makeGameSession } from '../../factories';

jest.mock('../../../src/repositories/BetRepository');
jest.mock('../../../src/repositories/UserRepository');
jest.mock('../../../src/services/WalletService');
jest.mock('../../../src/services/RiskService');
jest.mock('../../../src/services/GameSessionService');
jest.mock('../../../src/services/ConfigService');

const MockBetRepo          = BetRepository          as jest.MockedClass<typeof BetRepository>;
const MockUserRepo         = UserRepository         as jest.MockedClass<typeof UserRepository>;
const MockWalletService    = WalletService          as jest.MockedClass<typeof WalletService>;
const MockRiskService      = RiskService            as jest.MockedClass<typeof RiskService>;
const MockGameSessionSvc   = GameSessionService     as jest.MockedClass<typeof GameSessionService>;
const MockConfigService    = ConfigService          as jest.MockedClass<typeof ConfigService>;

const BASE_PARAMS = {
  userId:         'usr-1',
  gameId:         'game_slots_v1',
  amount:         '50.00',
  currency:       'USD',
  betType:        'slots',
  idempotencyKey: 'idem-place-1',
};

describe('BetService', () => {
  let service: BetService;
  let betRepo:        jest.Mocked<InstanceType<typeof BetRepository>>;
  let userRepo:       jest.Mocked<InstanceType<typeof UserRepository>>;
  let walletSvc:      jest.Mocked<InstanceType<typeof WalletService>>;
  let riskSvc:        jest.Mocked<InstanceType<typeof RiskService>>;
  let gameSessionSvc: jest.Mocked<InstanceType<typeof GameSessionService>>;
  let configSvc:      jest.Mocked<InstanceType<typeof ConfigService>>;

  beforeEach(() => {
    [MockBetRepo, MockUserRepo, MockWalletService, MockRiskService, MockGameSessionSvc, MockConfigService]
      .forEach((M) => M.mockClear());

    service = new BetService();

    betRepo        = MockBetRepo.mock.instances[0]        as any;
    userRepo       = MockUserRepo.mock.instances[0]       as any;
    walletSvc      = MockWalletService.mock.instances[0]  as any;
    riskSvc        = MockRiskService.mock.instances[0]    as any;
    gameSessionSvc = MockGameSessionSvc.mock.instances[0] as any;
    configSvc      = MockConfigService.mock.instances[0]  as any;

    // Happy-path defaults
    betRepo.findByIdempotencyKey.mockResolvedValue(null);
    userRepo.findById.mockResolvedValue(makeUser());
    userRepo.getLimits.mockResolvedValue(null);
    walletSvc.reserveForBet.mockResolvedValue(makeWalletTx({ type: 'bet_reserve' }));
    walletSvc.getBalance.mockResolvedValue({ ...makeWallet(), total: '1000.00' });
    walletSvc.settleBetWin.mockResolvedValue(undefined as any);
    walletSvc.settleBetLoss.mockResolvedValue(undefined as any);
    walletSvc.voidBetReserve.mockResolvedValue(undefined as any);
    betRepo.create.mockResolvedValue(makeBet());
    configSvc.isEnabled.mockResolvedValue(false); // risk eval off by default
  });

  // ── placeBet ───────────────────────────────────────────────────────────────

  describe('placeBet', () => {
    it('returns existing bet on idempotency hit', async () => {
      const existing = makeBet();
      betRepo.findByIdempotencyKey.mockResolvedValue(existing);

      const result = await service.placeBet(BASE_PARAMS);

      expect(result.bet).toBe(existing);
      expect(userRepo.findById).not.toHaveBeenCalled();
    });

    it('throws UserSuspendedError when account is suspended', async () => {
      userRepo.findById.mockResolvedValue(makeUser({ status: 'suspended' }));

      await expect(service.placeBet(BASE_PARAMS)).rejects.toThrow(UserSuspendedError);
    });

    it('throws KycRequiredError when KYC is not verified', async () => {
      userRepo.findById.mockResolvedValue(makeUser({ kycStatus: 'pending' }));

      await expect(service.placeBet(BASE_PARAMS)).rejects.toThrow(KycRequiredError);
    });

    it('throws BetLimitExceededError when stake exceeds daily limit', async () => {
      userRepo.getLimits.mockResolvedValue({ depositLimitDaily: '10.00' } as any);

      // 50 > 10 * 0.5 = 5
      await expect(service.placeBet(BASE_PARAMS)).rejects.toThrow(BetLimitExceededError);
    });

    it('throws RiskRejectedError when risk evaluator rejects', async () => {
      configSvc.isEnabled.mockResolvedValue(true);
      riskSvc.evaluate.mockResolvedValue({
        decision: 'reject',
        riskScore: 90,
        riskTier: 'blocked',
        flags: ['account_blocked'],
        evalId: 'eval-1',
      });

      await expect(service.placeBet(BASE_PARAMS)).rejects.toThrow(RiskRejectedError);
      expect(walletSvc.reserveForBet).not.toHaveBeenCalled();
    });

    it('places bet and reserves funds for allowed decision', async () => {
      const bet = makeBet({ betId: 'bet-placed' });
      betRepo.create.mockResolvedValue(bet);

      const result = await service.placeBet(BASE_PARAMS);

      expect(walletSvc.reserveForBet).toHaveBeenCalledWith(expect.objectContaining({
        userId: 'usr-1',
        amount: '50.00',
      }));
      expect(betRepo.create).toHaveBeenCalledWith(expect.objectContaining({
        userId:         'usr-1',
        gameId:         'game_slots_v1',
        idempotencyKey: 'idem-place-1',
      }));
      expect(result.bet.betId).toBe('bet-placed');
    });

    it('skips risk evaluation when feature flag is off', async () => {
      configSvc.isEnabled.mockResolvedValue(false);

      await service.placeBet(BASE_PARAMS);

      expect(riskSvc.evaluate).not.toHaveBeenCalled();
    });

    it('validates game session when gameSessionId is provided', async () => {
      const session = makeGameSession();
      gameSessionSvc.validateActiveSession.mockResolvedValue(session);
      betRepo.create.mockResolvedValue(makeBet());
      betRepo.findById.mockResolvedValue(makeBet());
      betRepo.settle.mockResolvedValue(makeBet({ status: 'settled' }));

      await service.placeBet({ ...BASE_PARAMS, gameSessionId: 'gsess-0001' });

      expect(gameSessionSvc.validateActiveSession).toHaveBeenCalledWith('gsess-0001', 'usr-1');
    });
  });

  // ── settleBet ──────────────────────────────────────────────────────────────

  describe('settleBet', () => {
    it('calls settleBetWin when payout > 0', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ status: 'accepted', amount: '50.00' }));
      betRepo.settle.mockResolvedValue(makeBet({ status: 'settled' }));

      await service.settleBet('bet-001', { payout: '100.00' });

      expect(walletSvc.settleBetWin).toHaveBeenCalledWith(expect.objectContaining({
        payout: '100.00',
        stakeAmount: '50.00',
        betId: 'bet-001',
      }));
    });

    it('calls settleBetLoss when payout is 0', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ status: 'accepted', amount: '50.00' }));
      betRepo.settle.mockResolvedValue(makeBet({ status: 'settled' }));

      await service.settleBet('bet-001', { payout: '0.00' });

      expect(walletSvc.settleBetLoss).toHaveBeenCalled();
      expect(walletSvc.settleBetWin).not.toHaveBeenCalled();
    });

    it('throws BetNotFoundError when bet does not exist', async () => {
      betRepo.findById.mockResolvedValue(null);

      await expect(service.settleBet('ghost-bet', { payout: '0.00' })).rejects.toThrow(BetNotFoundError);
    });

    it('throws BetAlreadySettledError when bet is already settled', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ status: 'settled' }));

      await expect(service.settleBet('bet-001', { payout: '0.00' })).rejects.toThrow(BetAlreadySettledError);
    });

    it('throws ForbiddenError when bet is voided', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ status: 'voided' }));

      await expect(service.settleBet('bet-001', { payout: '0.00' })).rejects.toThrow(ForbiddenError);
    });
  });

  // ── voidBet ────────────────────────────────────────────────────────────────

  describe('voidBet', () => {
    it('releases reserved funds and marks bet as voided', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ status: 'accepted', userId: 'usr-1' }));
      betRepo.void.mockResolvedValue(makeBet({ status: 'voided' }));

      const result = await service.voidBet('bet-0001', 'usr-1', false);

      expect(walletSvc.voidBetReserve).toHaveBeenCalledWith(expect.objectContaining({ betId: 'bet-0001' }));
      expect(result.status).toBe('voided');
    });

    it('throws ForbiddenError when non-admin accesses another user bet', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ userId: 'usr-other' }));

      await expect(service.voidBet('bet-0001', 'usr-1', false)).rejects.toThrow(ForbiddenError);
    });

    it('allows admin to void any bet', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ status: 'accepted', userId: 'usr-other' }));
      betRepo.void.mockResolvedValue(makeBet({ status: 'voided' }));

      await service.voidBet('bet-0001', 'admin-1', true);

      expect(walletSvc.voidBetReserve).toHaveBeenCalled();
    });

    it('throws ForbiddenError when bet is not in accepted status', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ status: 'settled' }));

      await expect(service.voidBet('bet-0001', 'usr-1', true)).rejects.toThrow(ForbiddenError);
    });
  });

  // ── getBet ─────────────────────────────────────────────────────────────────

  describe('getBet', () => {
    it('returns bet when owner requests it', async () => {
      const bet = makeBet({ userId: 'usr-1' });
      betRepo.findById.mockResolvedValue(bet);

      const result = await service.getBet('bet-0001', 'usr-1');
      expect(result).toBe(bet);
    });

    it('throws ForbiddenError when non-owner requests another user bet', async () => {
      betRepo.findById.mockResolvedValue(makeBet({ userId: 'usr-other' }));

      await expect(service.getBet('bet-0001', 'usr-1')).rejects.toThrow(ForbiddenError);
    });

    it('allows admin to view any bet', async () => {
      const bet = makeBet({ userId: 'usr-other' });
      betRepo.findById.mockResolvedValue(bet);

      const result = await service.getBet('bet-0001', 'admin-1', true);
      expect(result).toBe(bet);
    });

    it('throws BetNotFoundError when bet does not exist', async () => {
      betRepo.findById.mockResolvedValue(null);

      await expect(service.getBet('ghost', 'usr-1')).rejects.toThrow(BetNotFoundError);
    });
  });

  // ── getBetHistory ──────────────────────────────────────────────────────────

  describe('getBetHistory', () => {
    it('delegates to repo with provided options', async () => {
      betRepo.listByUser.mockResolvedValue({ bets: [], nextCursor: null } as any);

      await service.getBetHistory('usr-1', { limit: 5, status: 'settled' });

      expect(betRepo.listByUser).toHaveBeenCalledWith('usr-1', { limit: 5, status: 'settled' });
    });
  });
});
