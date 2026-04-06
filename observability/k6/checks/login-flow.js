/**
 * Synthetic: Login flow validation
 * Cadence: every 1 minute
 * Tags all traffic with x-synthetic: true for Istio 100% sampling + Grafana filtering
 */
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Trend, Rate } from 'k6/metrics';

export const options = {
  scenarios: {
    synthetic_login: {
      executor: 'constant-arrival-rate',
      rate: 1,
      timeUnit: '1m',
      duration: '0',        // run externally via K6 Operator CronJob
      preAllocatedVUs: 2,
    },
  },
  thresholds: {
    'http_req_duration{check:login}': ['p(99)<2000'],
    'http_req_failed{check:login}': ['rate<0.01'],
    'checks': ['rate>0.99'],
  },
  tags: {
    synthetic: 'true',
    check_name: 'login-flow',
    environment: __ENV.ENVIRONMENT || 'prod',
  },
};

const syntheticHeaders = {
  'Content-Type': 'application/json',
  'x-synthetic': 'true',
  'x-check-name': 'login-flow',
};

const BASE_URL = __ENV.BASE_URL || 'http://y_eet-platform-api.default.svc.cluster.local:8080';
const SYNTH_EMAIL = __ENV.SYNTH_EMAIL || 'synthetic@y_eet.internal';
const SYNTH_PASSWORD = __ENV.SYNTH_PASSWORD || 'SynthPassword123!';

const loginErrors = new Counter('synth_login_errors_total');
const loginDuration = new Trend('synth_login_duration_ms');
const loginSuccess = new Rate('synth_login_success_rate');

export default function () {
  // ── Step 1: Login ─────────────────────────────────────────────────────────
  const loginStart = Date.now();
  const loginRes = http.post(
    `${BASE_URL}/api/v1/auth/login`,
    JSON.stringify({ email: SYNTH_EMAIL, password: SYNTH_PASSWORD }),
    { headers: syntheticHeaders, tags: { check: 'login' } },
  );

  const loginOk = check(loginRes, {
    'login status 200': (r) => r.status === 200,
    'login returns access_token': (r) => {
      try { return JSON.parse(r.body).access_token !== undefined; } catch { return false; }
    },
    'login latency < 2s': (r) => r.timings.duration < 2000,
  });

  loginDuration.add(Date.now() - loginStart);
  loginSuccess.add(loginOk ? 1 : 0);

  if (!loginOk) {
    loginErrors.add(1, { step: 'login', status: String(loginRes.status) });
    return;
  }

  const { access_token } = JSON.parse(loginRes.body);
  const authHeaders = {
    ...syntheticHeaders,
    Authorization: `Bearer ${access_token}`,
  };

  // ── Step 2: Fetch wallet balance ──────────────────────────────────────────
  const walletRes = http.get(
    `${BASE_URL}/api/v1/wallet/balance`,
    { headers: authHeaders, tags: { check: 'wallet-balance' } },
  );

  check(walletRes, {
    'wallet balance status 200': (r) => r.status === 200,
    'wallet has balance field': (r) => {
      try { return JSON.parse(r.body).balance !== undefined; } catch { return false; }
    },
    'wallet read latency < 500ms': (r) => r.timings.duration < 500,
  });

  if (walletRes.status !== 200) {
    loginErrors.add(1, { step: 'wallet-read', status: String(walletRes.status) });
  }

  // ── Step 3: Refresh token ─────────────────────────────────────────────────
  const { refresh_token } = JSON.parse(loginRes.body);
  const refreshRes = http.post(
    `${BASE_URL}/api/v1/auth/refresh`,
    JSON.stringify({ refresh_token }),
    { headers: syntheticHeaders, tags: { check: 'token-refresh' } },
  );

  check(refreshRes, {
    'token refresh status 200': (r) => r.status === 200,
    'new access_token returned': (r) => {
      try { return JSON.parse(r.body).access_token !== undefined; } catch { return false; }
    },
  });

  if (refreshRes.status !== 200) {
    loginErrors.add(1, { step: 'token-refresh', status: String(refreshRes.status) });
  }

  sleep(1);
}
