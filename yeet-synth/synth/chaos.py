"""
Fault injection and chaos helpers.

These are OPTIONAL and ADDITIVE — they can be mixed into any traffic profile
by enabling chaos_enabled in the profile config.

All chaos scenarios are designed to be safe in staging:
  - They don't delete data
  - They don't bypass security controls that should remain active
  - They produce observable telemetry to verify alert pipelines

WARNING: Do NOT run chaos mode in production without explicit authorisation
and an active incident response channel open.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass

import synth.endpoints as ep

from .client import SynthClient
from .payloads import malformed_bet_payload, malformed_login_payload, stale_token
from .token_manager import TokenPool

logger = logging.getLogger(__name__)


@dataclass
class ChaosScenarioResult:
    scenario: str
    status_code: int
    expected_status: int
    passed: bool
    latency_ms: float
    note: str = ""


class ChaosInjector:
    """
    Runs a battery of chaos scenarios against the API.
    Returns a list of ChaosScenarioResults for evaluation.
    """

    def __init__(self, client: SynthClient, pool: TokenPool) -> None:
        self._client = client
        self._pool = pool

    async def run_all(self) -> list[ChaosScenarioResult]:
        results: list[ChaosScenarioResult] = []
        creds = self._pool.get_random()

        if creds:
            results += await self._stale_token_requests(creds.user_id)
            results += await self._malformed_payloads(creds.access_token)
            results += await self._duplicate_idempotency_replay(creds)
            results += await self._rate_limit_burst()
            results += await self._missing_idempotency_key(creds.access_token)
        else:
            logger.warning(
                "Chaos: no token available, skipping auth-required scenarios"
            )

        results += await self._unauthenticated_protected_endpoints()
        return results

    # ── 1. Stale / invalid token ──────────────────────────────────────────────

    async def _stale_token_requests(self, user_id: str) -> list[ChaosScenarioResult]:
        """All requests with an expired token must 401."""
        token = stale_token()
        r = await ep.users_profile(self._client, token, user_id)
        return [
            ChaosScenarioResult(
                scenario="stale_token",
                status_code=r.status_code,
                expected_status=401,
                passed=r.status_code == 401,
                latency_ms=r.latency_ms,
                note="Expired JWT must be rejected with 401",
            )
        ]

    # ── 2. Malformed payloads ─────────────────────────────────────────────────

    async def _malformed_payloads(self, token: str) -> list[ChaosScenarioResult]:
        results = []

        # Malformed bet
        r = await self._client.request(
            "POST",
            "/api/v1/bets/place",
            token=token,
            idempotency_key=str(uuid.uuid4()),
            json=malformed_bet_payload(),
            endpoint_name="POST /api/v1/bets/place [malformed]",
        )
        results.append(
            ChaosScenarioResult(
                scenario="malformed_bet_payload",
                status_code=r.status_code,
                expected_status=400,
                passed=r.status_code == 400,
                latency_ms=r.latency_ms,
                note="Invalid bet payload must return 400 VALIDATION_ERROR",
            )
        )

        # Malformed login
        r = await self._client.request(
            "POST",
            "/api/v1/auth/token",
            json=malformed_login_payload(),
            endpoint_name="POST /api/v1/auth/token [malformed]",
        )
        results.append(
            ChaosScenarioResult(
                scenario="malformed_login_payload",
                status_code=r.status_code,
                expected_status=400,
                passed=r.status_code == 400,
                latency_ms=r.latency_ms,
                note="Invalid login payload must return 400",
            )
        )

        # Oversized body (send 1001 bytes of garbage)
        garbage = {"data": "x" * 1001}
        r = await self._client.request(
            "POST",
            "/api/v1/auth/token",
            json=garbage,
            endpoint_name="POST /api/v1/auth/token [oversized]",
        )
        results.append(
            ChaosScenarioResult(
                scenario="oversized_body",
                status_code=r.status_code,
                expected_status=400,
                passed=r.status_code in (400, 413, 422),
                latency_ms=r.latency_ms,
                note="Oversized malformed body should be rejected",
            )
        )

        return results

    # ── 3. Idempotency replay ─────────────────────────────────────────────────

    async def _duplicate_idempotency_replay(self, creds) -> list[ChaosScenarioResult]:
        """Send the same request twice with the same idempotency key.
        Second must replay."""
        key = str(uuid.uuid4())
        r1 = await ep.wallet_deposit(
            self._client,
            creds.access_token,
            creds.user_id,
            amount="5.00",
            idempotency_key=key,
        )
        await asyncio.sleep(0.1)
        r2 = await ep.wallet_deposit(
            self._client,
            creds.access_token,
            creds.user_id,
            amount="5.00",
            idempotency_key=key,
        )

        return [
            ChaosScenarioResult(
                scenario="idempotency_replay",
                status_code=r2.status_code,
                expected_status=r1.status_code,
                passed=r2.idempotency_replay or r2.status_code == r1.status_code,
                latency_ms=r2.latency_ms,
                note=(
                    f"Replay detected={r2.idempotency_replay}; "
                    f"first={r1.status_code} second={r2.status_code}"
                ),
            )
        ]

    # ── 4. Rate limit burst ───────────────────────────────────────────────────

    async def _rate_limit_burst(self) -> list[ChaosScenarioResult]:
        """Fire > RATE_LIMIT_MAX requests in a short window to trigger 429."""
        tasks = [ep.health_live(self._client) for _ in range(120)]
        records = await asyncio.gather(*tasks)
        rate_limited = [r for r in records if r.status_code == 429]
        return [
            ChaosScenarioResult(
                scenario="rate_limit_trigger",
                status_code=429 if rate_limited else 200,
                expected_status=429,
                passed=len(rate_limited) > 0,
                latency_ms=0.0,
                note=f"{len(rate_limited)}/120 requests returned 429",
            )
        ]

    # ── 5. Missing idempotency key on guarded endpoint ────────────────────────

    async def _missing_idempotency_key(self, token: str) -> list[ChaosScenarioResult]:
        """Omit the Idempotency-Key header on an endpoint that requires it."""
        r = await self._client.request(
            "POST",
            "/api/v1/bets/place",
            token=token,
            # No idempotency_key= argument
            json={
                "game_id": "game_crash_v1",
                "amount": "1.00",
                "currency": "USD",
                "bet_type": "auto_cashout",
            },
            endpoint_name="POST /api/v1/bets/place [no-idem-key]",
        )
        return [
            ChaosScenarioResult(
                scenario="missing_idempotency_key",
                status_code=r.status_code,
                expected_status=400,
                passed=r.status_code == 400,
                latency_ms=r.latency_ms,
                note="Missing Idempotency-Key must return 400 MISSING_IDEMPOTENCY_KEY",
            )
        ]

    # ── 6. Unauthenticated access to protected endpoints ─────────────────────

    async def _unauthenticated_protected_endpoints(self) -> list[ChaosScenarioResult]:
        results = []
        protected = [
            ("/api/v1/bets/history", "GET"),
            ("/api/v1/wallet/00000000-0000-0000-0000-000000000000/balance", "GET"),
            ("/api/v1/config/flags", "GET"),
            ("/_internal/status", "GET"),
        ]
        for path, method in protected:
            r = await self._client.request(
                method,
                path,
                endpoint_name=f"{method} {path} [no-auth]",
                # No token
            )
            results.append(
                ChaosScenarioResult(
                    scenario=f"unauth_{path.split('/')[-1]}",
                    status_code=r.status_code,
                    expected_status=401,
                    passed=r.status_code in (401, 403),
                    latency_ms=r.latency_ms,
                    note=f"{method} {path} without auth must 401/403",
                )
            )
        return results
