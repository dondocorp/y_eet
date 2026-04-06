import CircuitBreaker from 'opossum';
import { v4 as uuidv4 } from 'uuid';
import { RiskRepository } from '../repositories/RiskRepository';
import { ConfigRepository } from '../repositories/ConfigRepository';
import { RiskEvaluationRequest, RiskEvaluationResult } from '../types';
import { riskEvaluationsTotal, riskEvalDuration, riskCircuitBreakerOpen } from '../telemetry/metrics';
import { config } from '../config';

export class RiskService {
  private repo: RiskRepository;
  private configRepo: ConfigRepository;
  private breaker: CircuitBreaker;

  constructor() {
    this.repo = new RiskRepository();
    this.configRepo = new ConfigRepository();

    this.breaker = new CircuitBreaker(
      async (req: RiskEvaluationRequest) => this.evaluateInternal(req),
      {
        timeout: config.RISK_EVAL_TIMEOUT_MS,
        errorThresholdPercentage: 30,
        resetTimeout: 15000,
        volumeThreshold: 5,
        name: 'risk-evaluation',
      },
    );

    this.breaker.on('open', () => {
      riskCircuitBreakerOpen.add(1);
      console.warn('Risk service circuit breaker opened');
    });

    // Fail closed: when circuit opens, reject the bet
    this.breaker.fallback((_req: RiskEvaluationRequest) => ({
      decision: 'reject' as const,
      riskScore: 100,
      riskTier: 'blocked' as const,
      flags: ['risk_service_unavailable'],
      evalId: uuidv4(),
    }));
  }

  async evaluate(req: RiskEvaluationRequest): Promise<RiskEvaluationResult> {
    const start = Date.now();
    const result = await this.breaker.fire(req) as RiskEvaluationResult;

    riskEvaluationsTotal.add(1, { decision: result.decision });
    riskEvalDuration.record(Date.now() - start);

    return result;
  }

  async ingestSignal(params: {
    userId: string;
    signalType: string;
    severity: 'low' | 'medium' | 'high' | 'critical';
    context?: Record<string, unknown>;
  }): Promise<string> {
    return this.repo.ingestSignal({
      userId: params.userId,
      signalType: params.signalType,
      severity: params.severity,
      context: params.context,
      occurredAt: new Date(),
    });
  }

  async getRiskScore(userId: string): Promise<{ riskScore: number; riskTier: string; flags: string[] }> {
    const profile = await this.repo.getProfile(userId);
    return {
      riskScore: profile?.riskScore ?? 0,
      riskTier: profile?.riskTier ?? 'standard',
      flags: profile?.flags ?? [],
    };
  }

  // ─── Internal evaluation logic ────────────────────────────────────────────

  private async evaluateInternal(req: RiskEvaluationRequest): Promise<RiskEvaluationResult> {
    const evalId = uuidv4();
    const flags: string[] = [];
    let riskScore = 0;

    // Load existing risk profile
    const profile = await this.repo.getProfile(req.userId);
    riskScore = profile?.riskScore ?? 0;

    if (req.action === 'bet_place' && req.amount) {
      const stake = parseFloat(req.amount);

      // Flag 1: High-value single bet
      if (stake >= 1000) {
        flags.push('high_value_bet');
        riskScore += 20;
      }

      // Flag 2: Rapid bet velocity (>30 bets in 60s)
      const recentBets = await this.repo.countBetsInWindow(req.userId, 60);
      if (recentBets > 30) {
        flags.push('high_bet_velocity');
        riskScore += 30;
        // Async signal ingestion
        this.repo.ingestSignal({
          userId: req.userId,
          signalType: 'rapid_bet_sequence',
          severity: 'medium',
          context: { bets_in_60s: recentBets },
          occurredAt: new Date(),
        }).catch(() => {/* non-fatal */});
      }

      // Flag 3: Daily loss limit approach
      const todayLosses = await this.repo.sumLossesToday(req.userId);
      const lossLimit = profile ? 1000 : null; // simplified; real impl checks user_limits table
      if (lossLimit && parseFloat(todayLosses) + stake > lossLimit * 0.8) {
        flags.push('approaching_loss_limit');
        riskScore += 10;
      }

      // Flag 4: Risk tier blocked
      if (profile?.riskTier === 'blocked') {
        flags.push('account_blocked');
        riskScore = 100;
      }
    }

    // Clamp score
    riskScore = Math.min(100, riskScore);

    const tier = riskScore >= 80
      ? 'blocked'
      : riskScore >= 60
        ? 'high'
        : riskScore >= 40
          ? 'elevated'
          : riskScore >= 20
            ? 'standard'
            : 'low';

    const decision: RiskEvaluationResult['decision'] =
      riskScore >= 80 ? 'reject' : riskScore >= 60 ? 'review' : 'allow';

    // Update risk profile asynchronously
    this.repo.upsertProfile({
      userId: req.userId,
      riskScore,
      riskTier: tier as RiskEvaluationResult['riskTier'],
      flags,
    }).catch(() => {/* non-fatal */});

    return { decision, riskScore, riskTier: tier as RiskEvaluationResult['riskTier'], flags, evalId };
  }
}
