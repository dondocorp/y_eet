/**
 * Synthetic: Bet placement dry-run validation
 * Uses a dedicated synthetic user account with pre-seeded balance.
 * Cadence: every 2 minutes
 * Always traces (x-synthetic: true → Istio 100% sampling)
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend, Rate } from 'k6/metrics';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  scenarios: {
    synthetic_bet: {
      executor: 'constant-arrival-rate',
      rate: 1,
      timeUnit: '2m',
      duration: '0',
      preAllocatedVUs: 2,
    },
  },
  thresholds: {
    'synth_bet_duration_ms': ['p(99)<3000'],
    'synth_bet_success_rate': ['rate>0.99'],
  },
  tags: {
    synthetic: 'true',
    check_name: 'bet-placement-dryrun',
    environment: __ENV.ENVIRONMENT || 'prod',
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://y_eet-platform-api.default.svc.cluster.local:8080';
const SYNTH_EMAIL = __ENV.SYNTH_BET_EMAIL || 'synthetic-bet@y_eet.internal';
const SYNTH_PASSWORD = __ENV.SYNTH_BET_PASSWORD || 'SynthBetPassword123!';

const syntheticHeaders = {
  'Content-Type': 'application/json',
  'x-synthetic': 'true',
  'x-check-name': 'bet-placement-dryrun',
};

const betErrors = new Counter('synth_bet_errors_total');
const betDuration = new Trend('synth_bet_duration_ms');
const betSuccess = new Rate('synth_bet_success_rate');

export default function () {
  // ── Step 1: Authenticate ──────────────────────────────────────────────────
  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: SYNTH_EMAIL, password: SYNTH_PASSWORD }),
    { headers: syntheticHeaders },
  );

  if (loginRes.status !== 200) {
    betErrors.add(1, { step: 'auth' });
    return;
  }

  const { access_token } = JSON.parse(loginRes.body);
  const authHeaders = {
    ...syntheticHeaders,
    Authorization: `Bearer ${access_token}`,
  };

  // ── Step 2: Place minimal bet ($0.01 — synthetic user has reserved budget) ─
  const idempotencyKey = `synth-${uuidv4()}`;
  const betStart = Date.now();

  const betRes = http.post(
    `${BASE_URL}/api/v1/bets/place`,
    JSON.stringify({
      game_id: 'game_slots_synthetic',
      amount: '0.01',
      currency: 'USD',
      bet_type: 'synthetic_dryrun',
      parameters: { synthetic: true, auto_cashout: 1.0 },
    }),
    {
      headers: {
        ...authHeaders,
        'Idempotency-Key': idempotencyKey,
      },
      tags: { check: 'bet-place' },
    },
  );

  const betOk = check(betRes, {
    'bet placement status 202': (r) => r.status === 202,
    'bet_id returned': (r) => {
      try { return JSON.parse(r.body).bet_id !== undefined; } catch { return false; }
    },
    'trace_id in response': (r) => {
      try { return JSON.parse(r.body).trace_id !== undefined; } catch { return false; }
    },
    'bet latency < 3s': (r) => r.timings.duration < 3000,
  });

  betDuration.add(Date.now() - betStart);
  betSuccess.add(betOk ? 1 : 0);

  if (!betOk) {
    betErrors.add(1, {
      step: 'bet-place',
      status: String(betRes.status),
      body: betRes.body.substring(0, 200),
    });
  }

  // ── Step 3: Verify bet is retrievable ────────────────────────────────────
  if (betOk) {
    const { bet_id } = JSON.parse(betRes.body);
    const getRes = http.get(
      `${BASE_URL}/api/v1/bets/${bet_id}`,
      { headers: authHeaders, tags: { check: 'bet-get' } },
    );

    check(getRes, {
      'bet GET status 200': (r) => r.status === 200,
      'bet status is settled or accepted': (r) => {
        try {
          const body = JSON.parse(r.body);
          return ['accepted', 'settled'].includes(body.status);
        } catch { return false; }
      },
    });
  }

  sleep(2);
}
