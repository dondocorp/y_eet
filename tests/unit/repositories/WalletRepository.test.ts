import { WalletRepository } from '../../../src/repositories/WalletRepository';
import { InsufficientFundsError, WalletNotFoundError } from '../../../src/errors';

/**
 * These tests verify the transaction-level logic of WalletRepository
 * by mocking withTransaction and the pool client directly.
 */

// Mock the pool module
jest.mock('../../../src/db/pool', () => {
  const mockClient = {
    query:   jest.fn(),
    release: jest.fn(),
  };
  return {
    pool:            { query: jest.fn() },
    withTransaction: jest.fn(async (fn: (client: typeof mockClient) => unknown) => fn(mockClient)),
    __mockClient:    mockClient,
  };
});

import * as poolModule from '../../../src/db/pool';

const getClient = () => (poolModule as any).__mockClient as { query: jest.Mock; release: jest.Mock };

// Minimal row factories matching DB column names
const walletRow = (overrides = {}) => ({
  wallet_id:  'wallet-0001',
  user_id:    'usr-1',
  currency:   'USD',
  balance:    '1000.00',
  reserved:   '0.00',
  created_at: new Date(),
  updated_at: new Date(),
  ...overrides,
});

const txRow = (overrides = {}) => ({
  tx_id:           'tx-0001',
  wallet_id:       'wallet-0001',
  user_id:         'usr-1',
  type:            'bet_reserve',
  amount:          '-50.00',
  balance_after:   '950.00',
  reference_id:    'bet-0001',
  idempotency_key: 'idem-0001',
  metadata:        null,
  created_at:      new Date(),
  ...overrides,
});

describe('WalletRepository', () => {
  let repo: WalletRepository;
  let client: ReturnType<typeof getClient>;

  beforeEach(() => {
    repo   = new WalletRepository();
    client = getClient();
    client.query.mockReset();
    (poolModule.pool as any).query.mockReset();
  });

  // ── debit ──────────────────────────────────────────────────────────────────

  describe('debit', () => {
    const DEBIT_PARAMS = {
      userId:         'usr-1',
      amount:         '50.00',
      type:           'bet_reserve' as const,
      referenceId:    'bet-001',
      idempotencyKey: 'idem-001',
    };

    it('returns existing tx on idempotency hit', async () => {
      const existing = txRow();
      client.query
        .mockResolvedValueOnce({ rows: [existing] }); // idempotency check

      const result = await repo.debit(DEBIT_PARAMS);

      expect(result.txId).toBe('tx-0001');
      // Should NOT query wallet or insert
      expect(client.query).toHaveBeenCalledTimes(1);
    });

    it('debits balance and creates transaction record', async () => {
      const newTxRow = txRow({ balance_after: '950.00' });
      client.query
        .mockResolvedValueOnce({ rows: [] })              // idempotency miss
        .mockResolvedValueOnce({ rows: [walletRow()] })   // SELECT FOR UPDATE
        .mockResolvedValueOnce({ rows: [newTxRow] })      // INSERT tx
        .mockResolvedValueOnce({ rows: [] });             // UPDATE balance

      const result = await repo.debit(DEBIT_PARAMS);

      expect(result.balanceAfter).toBe('950.00');
      expect(client.query).toHaveBeenCalledTimes(4);
    });

    it('throws InsufficientFundsError when balance is too low', async () => {
      client.query
        .mockResolvedValueOnce({ rows: [] })                          // idempotency miss
        .mockResolvedValueOnce({ rows: [walletRow({ balance: '10.00' })] }); // not enough

      await expect(repo.debit(DEBIT_PARAMS)).rejects.toThrow(InsufficientFundsError);
    });

    it('throws WalletNotFoundError when wallet does not exist', async () => {
      client.query
        .mockResolvedValueOnce({ rows: [] }) // idempotency miss
        .mockResolvedValueOnce({ rows: [] }); // no wallet

      await expect(repo.debit(DEBIT_PARAMS)).rejects.toThrow(WalletNotFoundError);
    });

    it('increments reserved amount for bet_reserve type', async () => {
      client.query
        .mockResolvedValueOnce({ rows: [] })
        .mockResolvedValueOnce({ rows: [walletRow({ balance: '1000.00', reserved: '100.00' })] })
        .mockResolvedValueOnce({ rows: [txRow()] })
        .mockResolvedValueOnce({ rows: [] });

      await repo.debit(DEBIT_PARAMS);

      // 3rd call is INSERT, 4th is UPDATE with new reserved value
      const updateCall = client.query.mock.calls[3];
      expect(updateCall[1][1]).toBe('150.00'); // 100 + 50
    });
  });

  // ── credit ─────────────────────────────────────────────────────────────────

  describe('credit', () => {
    const CREDIT_PARAMS = {
      userId:          'usr-1',
      amount:          '100.00',
      type:            'deposit' as const,
      referenceId:     'stripe-pi-1',
      idempotencyKey:  'idem-credit-1',
    };

    it('returns existing tx on idempotency hit', async () => {
      client.query.mockResolvedValueOnce({ rows: [txRow({ type: 'deposit', amount: '100.00' })] });

      const result = await repo.credit(CREDIT_PARAMS);
      expect(result.txId).toBe('tx-0001');
      expect(client.query).toHaveBeenCalledTimes(1);
    });

    it('credits balance and creates transaction record', async () => {
      const newTxRow = txRow({ type: 'deposit', amount: '100.00', balance_after: '1100.00' });
      client.query
        .mockResolvedValueOnce({ rows: [] })             // idempotency miss
        .mockResolvedValueOnce({ rows: [walletRow()] })  // SELECT FOR UPDATE
        .mockResolvedValueOnce({ rows: [newTxRow] })     // INSERT tx
        .mockResolvedValueOnce({ rows: [] });            // UPDATE balance

      const result = await repo.credit(CREDIT_PARAMS);
      expect(result.balanceAfter).toBe('1100.00');
    });

    it('releases reserved funds when releaseReserved is set', async () => {
      client.query
        .mockResolvedValueOnce({ rows: [] })
        .mockResolvedValueOnce({ rows: [walletRow({ balance: '950.00', reserved: '50.00' })] })
        .mockResolvedValueOnce({ rows: [txRow({ type: 'bet_win', balance_after: '1000.00' })] })
        .mockResolvedValueOnce({ rows: [] });

      await repo.credit({ ...CREDIT_PARAMS, amount: '50.00', type: 'bet_win', releaseReserved: '50.00' });

      const updateCall = client.query.mock.calls[3];
      expect(updateCall[1][1]).toBe('0.00'); // 50.00 reserved - 50.00 released
    });

    it('throws WalletNotFoundError when wallet does not exist', async () => {
      client.query
        .mockResolvedValueOnce({ rows: [] }) // idempotency miss
        .mockResolvedValueOnce({ rows: [] }); // no wallet

      await expect(repo.credit(CREDIT_PARAMS)).rejects.toThrow(WalletNotFoundError);
    });
  });

  // ── getTransactions ────────────────────────────────────────────────────────

  describe('getTransactions', () => {
    it('returns transactions and no cursor when within page limit', async () => {
      const rows = [txRow(), txRow({ tx_id: 'tx-0002' })];
      (poolModule.pool as any).query.mockResolvedValue({ rows });

      const result = await repo.getTransactions('usr-1', { limit: 10 });

      expect(result.transactions).toHaveLength(2);
      expect(result.nextCursor).toBeNull();
    });

    it('returns nextCursor when there are more results', async () => {
      // Fetch limit+1 rows to detect more pages
      const rows = Array.from({ length: 11 }, (_, i) =>
        txRow({ tx_id: `tx-${i}`, created_at: new Date(Date.now() - i * 1000) }),
      );
      (poolModule.pool as any).query.mockResolvedValue({ rows });

      const result = await repo.getTransactions('usr-1', { limit: 10 });

      expect(result.transactions).toHaveLength(10);
      expect(result.nextCursor).not.toBeNull();
    });
  });
});
