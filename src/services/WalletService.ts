import { WalletRepository } from '../repositories/WalletRepository';
import { WalletAccount, WalletTransaction } from '../types';
import { WalletNotFoundError } from '../errors';
import { walletTransfersTotal, walletTransferDuration, walletBalanceReadDuration } from '../telemetry/metrics';

export class WalletService {
  private repo: WalletRepository;

  constructor() {
    this.repo = new WalletRepository();
  }

  async getBalance(userId: string): Promise<WalletAccount & { total: string }> {
    const start = Date.now();
    const wallet = await this.repo.getByUserId(userId);
    walletBalanceReadDuration.record(Date.now() - start);
    if (!wallet) throw new WalletNotFoundError(userId);
    return {
      ...wallet,
      total: (parseFloat(wallet.balance) + parseFloat(wallet.reserved)).toFixed(2),
    };
  }

  async deposit(params: {
    userId: string;
    amount: string;
    idempotencyKey: string;
    paymentReference?: string;
    metadata?: Record<string, unknown>;
  }): Promise<WalletTransaction> {
    const start = Date.now();
    const tx = await this.repo.credit({
      userId: params.userId,
      amount: params.amount,
      type: 'deposit',
      referenceId: params.paymentReference ?? params.idempotencyKey,
      idempotencyKey: params.idempotencyKey,
      metadata: params.metadata,
    });
    walletTransfersTotal.add(1, { type: 'deposit', status: 'success' });
    walletTransferDuration.record(Date.now() - start, { type: 'deposit' });
    return tx;
  }

  async withdraw(params: {
    userId: string;
    amount: string;
    idempotencyKey: string;
    destinationId?: string;
  }): Promise<WalletTransaction> {
    const start = Date.now();
    const tx = await this.repo.debit({
      userId: params.userId,
      amount: params.amount,
      type: 'withdrawal',
      referenceId: params.destinationId ?? params.idempotencyKey,
      idempotencyKey: params.idempotencyKey,
    });
    walletTransfersTotal.add(1, { type: 'withdrawal', status: 'success' });
    walletTransferDuration.record(Date.now() - start, { type: 'withdrawal' });
    return tx;
  }

  async reserveForBet(params: {
    userId: string;
    amount: string;
    betId: string;
  }): Promise<WalletTransaction> {
    return this.repo.debit({
      userId: params.userId,
      amount: params.amount,
      type: 'bet_reserve',
      referenceId: params.betId,
      idempotencyKey: `reserve_${params.betId}`,
    });
  }

  async settleBetWin(params: {
    userId: string;
    payout: string;
    stakeAmount: string;
    betId: string;
  }): Promise<WalletTransaction> {
    return this.repo.credit({
      userId: params.userId,
      amount: params.payout,
      type: 'bet_win',
      referenceId: params.betId,
      idempotencyKey: `settle_win_${params.betId}`,
      releaseReserved: params.stakeAmount,
    });
  }

  async settleBetLoss(params: {
    userId: string;
    stakeAmount: string;
    betId: string;
  }): Promise<void> {
    // On a loss, the reserved amount is already held — we just need to
    // move it from reserved to the house. We do a zero-value credit to release reserved.
    await this.repo.credit({
      userId: params.userId,
      amount: '0.00',
      type: 'bet_release',
      referenceId: params.betId,
      idempotencyKey: `settle_loss_${params.betId}`,
      releaseReserved: params.stakeAmount,
    });
  }

  async voidBetReserve(params: {
    userId: string;
    stakeAmount: string;
    betId: string;
  }): Promise<void> {
    // Return reserved funds back to available balance
    await this.repo.credit({
      userId: params.userId,
      amount: params.stakeAmount,
      type: 'adjustment',
      referenceId: params.betId,
      idempotencyKey: `void_${params.betId}`,
      releaseReserved: params.stakeAmount,
    });
  }

  async getTransactions(
    userId: string,
    opts: { limit?: number; cursor?: string; type?: string } = {},
  ): Promise<{ transactions: WalletTransaction[]; nextCursor: string | null }> {
    return this.repo.getTransactions(userId, opts);
  }
}
