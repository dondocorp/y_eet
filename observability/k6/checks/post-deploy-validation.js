/**
 * Post-deploy validation — runs once after each deployment.
 * Called from GitLab CI pipeline. Fails the pipeline on any check failure.
 * Covers: health, auth, wallet read, bet placement trace continuity.
 */
import http from 'k6/http';
import { check, group, fail } from 'k6';

export const options = {
  vus: 1,
  iterations: 1,
  thresholds: {
    'checks': ['rate==1.0'],    // all checks must pass
    'http_req_duration': ['p(99)<5000'],
  },
  tags: {
    synthetic: 'true',
    check_name: 'post-deploy-validation',
    trigger: 'ci',
  },
};

const BASE_URL = __ENV.BASE_URL;
const SYNTH_EMAIL = __ENV.SYNTH_EMAIL;
const SYNTH_PASSWORD = __ENV.SYNTH_PASSWORD;

const syntheticHeaders = {
  'Content-Type': 'application/json',
  'x-synthetic': 'true',
  'x-check-name': 'post-deploy-validation',
};

export default function () {
  let accessToken;

  // ── Health checks ─────────────────────────────────────────────────────────
  group('health', () => {
    const liveRes = http.get(`${BASE_URL}/health/live`, { headers: syntheticHeaders });
    if (!check(liveRes, { 'liveness 200': (r) => r.status === 200 })) {
      fail('Liveness check failed — service is not alive');
    }

    const readyRes = http.get(`${BASE_URL}/health/ready`, { headers: syntheticHeaders });
    if (!check(readyRes, { 'readiness 200': (r) => r.status === 200 })) {
      fail('Readiness check failed — service is not ready (DB connection?)');
    }
  });

  // ── Auth ──────────────────────────────────────────────────────────────────
  group('auth', () => {
    const res = http.post(
      `${BASE_URL}/api/v1/auth/login`,
      JSON.stringify({ email: SYNTH_EMAIL, password: SYNTH_PASSWORD }),
      { headers: syntheticHeaders },
    );

    if (!check(res, {
      'login 200': (r) => r.status === 200,
      'login has tokens': (r) => {
        try {
          const b = JSON.parse(r.body);
          return b.access_token && b.refresh_token;
        } catch { return false; }
      },
    })) {
      fail('Auth check failed — login endpoint broken');
    }

    accessToken = JSON.parse(res.body).access_token;
  });

  const authHeaders = { ...syntheticHeaders, Authorization: `Bearer ${accessToken}` };

  // ── Wallet read ───────────────────────────────────────────────────────────
  group('wallet', () => {
    const res = http.get(`${BASE_URL}/api/v1/wallet/balance`, { headers: authHeaders });
    check(res, {
      'wallet balance 200': (r) => r.status === 200,
      'wallet has numeric balance': (r) => {
        try { return !isNaN(parseFloat(JSON.parse(r.body).balance)); } catch { return false; }
      },
    });
  });

  // ── Bet placement (trace continuity) ──────────────────────────────────────
  group('bet-placement', () => {
    const res = http.post(
      `${BASE_URL}/api/v1/bets/place`,
      JSON.stringify({
        game_id: 'game_slots_synthetic',
        amount: '0.01',
        currency: 'USD',
        bet_type: 'post_deploy_validation',
        parameters: { synthetic: true, auto_cashout: 1.0 },
      }),
      {
        headers: {
          ...authHeaders,
          'Idempotency-Key': `post-deploy-${Date.now()}`,
        },
      },
    );

    check(res, {
      'bet placement 202': (r) => r.status === 202,
      'bet has trace_id': (r) => {
        try { return JSON.parse(r.body).trace_id !== undefined; } catch { return false; }
      },
    });
  });
}
