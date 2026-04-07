import { WalletService } from '../../../src/services/WalletService';
import { WalletRepository } from '../../../src/repositories/WalletRepository';
import { InsufficientFundsError, WalletNotFoundError } from '../../../src/errors';
import { makeWallet, makeWalletTx } from '../../factories';

jest.mock('../../../src/repositories/WalletRepository');

const MockWalletRepo = WalletRepository as jest.MockedClass<typeof WalletRepository>;

describe('WalletService', () => {
  let service: WalletService;
  let repo: jest.Mocked<InstanceType<typeof WalletRepository>>;

  beforeEach(() => {
    MockWalletRepo.mockClear();
    service = new WalletService();
    repo    = MockWalletRepo.mock.instances[0] as any;
  });

  // ── getBalance ─────────────────────────────────────────────────────────────

  describe('getBalance', () => {
    it('returns wallet with computed total', async () => {
      repo.getByUserId.mockResolvedValue(makeWallet({ balance: '500.00', reserved: '50.00' }));

      const result = await service.getBalance('usr-1');

      expect(result.balance).toBe('500.00');
      expect(result.reserved).toBe('50.00');
      expect(result.total).toBe('550.00');
    });

    it('throws WalletNotFoundError when wallet does not exist', async () => {
      repo.getByUserId.mockResolvedValue(null);

      await expect(service.getBalance('unknown')).rejects.toThrow(WalletNotFoundError);
    });

    it('computes total correctly when reserved is zero', async () => {
      repo.getByUserId.mockResolvedValue(makeWallet({ balance: '1000.00', reserved: '0.00' }));

      const result = await service.getBalance('usr-1');
      expect(result.total).toBe('1000.00');
    });
  });

  // ── deposit ────────────────────────────────────────────────────────────────

  describe('deposit', () => {
    it('calls repo.credit with correct params', async () => {
      const tx = makeWalletTx({ type: 'deposit', amount: '100.00', balanceAfter: '1100.00' });
      repo.credit.mockResolvedValue(tx);

      const result = await service.deposit({
        userId:         'usr-1',
        amount:         '100.00',
        idempotencyKey: 'dep-idem-1',
      });

      expect(repo.credit).toHaveBeenCalledWith(expect.objectContaining({
        userId:         'usr-1',
        amount:         '100.00',
        type:           'deposit',
        idempotencyKey: 'dep-idem-1',
      }));
      expect(result.balanceAfter).toBe('1100.00');
    });

    it('passes payment reference through to repo', async () => {
      repo.credit.mockResolvedValue(makeWalletTx());

      await service.deposit({
        userId:           'usr-1',
        amount:           '200.00',
        idempotencyKey:   'dep-idem-2',
        paymentReference: 'stripe_pi_xyz',
      });

      expect(repo.credit).toHaveBeenCalledWith(expect.objectContaining({
        referenceId: 'stripe_pi_xyz',
      }));
    });
  });

  // ── withdraw ───────────────────────────────────────────────────────────────

  describe('withdraw', () => {
    it('calls repo.debit with correct type', async () => {
      repo.debit.mockResolvedValue(makeWalletTx({ type: 'withdrawal' }));

      await service.withdraw({ userId: 'usr-1', amount: '50.00', idempotencyKey: 'wd-1' });

      expect(repo.debit).toHaveBeenCalledWith(expect.objectContaining({
        type: 'withdrawal',
        userId: 'usr-1',
        amount: '50.00',
      }));
    });

    it('propagates InsufficientFundsError from repository', async () => {
      repo.debit.mockRejectedValue(new InsufficientFundsError('30.00', '50.00'));

      await expect(
        service.withdraw({ userId: 'usr-1', amount: '50.00', idempotencyKey: 'wd-1' }),
      ).rejects.toThrow(InsufficientFundsError);
    });
  });

  // ── reserveForBet ──────────────────────────────────────────────────────────

  describe('reserveForBet', () => {
    it('uses bet_reserve type with correct idempotency key', async () => {
      repo.debit.mockResolvedValue(makeWalletTx({ type: 'bet_reserve' }));

      await service.reserveForBet({ userId: 'usr-1', amount: '25.00', betId: 'bet-001' });

      expect(repo.debit).toHaveBeenCalledWith(expect.objectContaining({
        type:           'bet_reserve',
        amount:         '25.00',
        idempotencyKey: 'reserve_bet-001',
        referenceId:    'bet-001',
      }));
    });

    it('propagates InsufficientFundsError', async () => {
      repo.debit.mockRejectedValue(new InsufficientFundsError('10.00', '25.00'));

      await expect(
        service.reserveForBet({ userId: 'usr-1', amount: '25.00', betId: 'bet-001' }),
      ).rejects.toThrow(InsufficientFundsError);
    });
  });

  // ── settleBetWin ───────────────────────────────────────────────────────────

  describe('settleBetWin', () => {
    it('credits payout and releases reserved stake', async () => {
      repo.credit.mockResolvedValue(makeWalletTx({ type: 'bet_win', amount: '50.00' }));

      await service.settleBetWin({
        userId:      'usr-1',
        payout:      '50.00',
        stakeAmount: '25.00',
        betId:       'bet-001',
      });

      expect(repo.credit).toHaveBeenCalledWith(expect.objectContaining({
        type:            'bet_win',
        amount:          '50.00',
        releaseReserved: '25.00',
        idempotencyKey:  'settle_win_bet-001',
      }));
    });
  });

  // ── settleBetLoss ──────────────────────────────────────────────────────────

  describe('settleBetLoss', () => {
    it('releases reserved funds with a zero-value credit', async () => {
      repo.credit.mockResolvedValue(makeWalletTx({ type: 'bet_release', amount: '0.00' }));

      await service.settleBetLoss({ userId: 'usr-1', stakeAmount: '25.00', betId: 'bet-001' });

      expect(repo.credit).toHaveBeenCalledWith(expect.objectContaining({
        amount:          '0.00',
        type:            'bet_release',
        releaseReserved: '25.00',
        idempotencyKey:  'settle_loss_bet-001',
      }));
    });
  });

  // ── voidBetReserve ─────────────────────────────────────────────────────────

  describe('voidBetReserve', () => {
    it('returns stake to available balance', async () => {
      repo.credit.mockResolvedValue(makeWalletTx({ type: 'adjustment' }));

      await service.voidBetReserve({ userId: 'usr-1', stakeAmount: '25.00', betId: 'bet-001' });

      expect(repo.credit).toHaveBeenCalledWith(expect.objectContaining({
        type:            'adjustment',
        amount:          '25.00',
        releaseReserved: '25.00',
        idempotencyKey:  'void_bet-001',
      }));
    });
  });

  // ── getTransactions ────────────────────────────────────────────────────────

  describe('getTransactions', () => {
    it('delegates to repo with default limit', async () => {
      repo.getTransactions.mockResolvedValue({ transactions: [], nextCursor: null });

      await service.getTransactions('usr-1');

      expect(repo.getTransactions).toHaveBeenCalledWith('usr-1', {});
    });

    it('passes options through to repo', async () => {
      repo.getTransactions.mockResolvedValue({ transactions: [], nextCursor: null });

      await service.getTransactions('usr-1', { limit: 10, type: 'deposit' });

      expect(repo.getTransactions).toHaveBeenCalledWith('usr-1', { limit: 10, type: 'deposit' });
    });
  });
});
