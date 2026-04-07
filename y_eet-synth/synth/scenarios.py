"""
User behaviour scenarios.

Each scenario models a realistic sequence of API calls made by
a particular type of user. Scenarios are the primary unit of
traffic composition — the runner picks scenarios by weight.

Archetypes:
  anonymous        — unauthenticated probing (health, warmup)
  authenticated    — login → profile → config → logout
  active_bettor    — full game flow: session → bets → close
  wallet_heavy     — deposit → check balance → withdraw → history
  admin            — internal diagnostic endpoints
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from typing import Optional

import synth.endpoints as ep

from .client import SynthClient
from .payloads import FLAG_KEYS, LIVE_GAME_IDS, register_payload
from .token_manager import TokenPool


def _amt(lo: float, hi: float) -> str:
    return f"{random.uniform(lo, hi):.2f}"

logger = logging.getLogger(__name__)


@dataclass
class ScenarioResult:
    scenario: str
    requests: int = 0
    successes: int = 0
    errors: int = 0
    skipped: bool = False
    skip_reason: str = ""

    @property
    def success_rate(self) -> float:
        return self.successes / self.requests if self.requests > 0 else 0.0


async def _think(min_ms: float = 50, max_ms: float = 300) -> None:
    """Simulate inter-request think time."""
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000.0)


class AnonymousScenario:
    """
    Unauthenticated traffic: health probes and warm-path checks.
    Models load balancers, monitoring agents, and pre-auth browsers.
    """

    name = "anonymous"

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)

        checks = [ep.health_live, ep.health_ready, ep.health_dependencies]
        for fn in checks:
            r = await fn(client)
            result.requests += 1
            if 200 <= r.status_code < 300:
                result.successes += 1
            else:
                result.errors += 1
            await _think(10, 80)

        return result


class AuthenticatedUserScenario:
    """
    Standard authenticated user flow:
    login → validate session → fetch profile → check limits → fetch flags → logout

    Represents casual users checking account status or browsing.
    """

    name = "authenticated"

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)
        creds = pool.get_random()
        if not creds:
            result.skipped = True
            result.skip_reason = "empty token pool"
            return result

        await pool.maybe_refresh(creds)
        token = creds.access_token
        user_id = creds.user_id

        steps = [
            lambda: ep.auth_session_validate(client, token),
            lambda: ep.users_profile(client, token, user_id),
            lambda: ep.users_limits(client, token, user_id),
            lambda: ep.config_flags(client, token),
            lambda: ep.config_flag(client, token, random.choice(FLAG_KEYS)),
        ]
        for step in steps:
            r = await step()
            result.requests += 1
            if 200 <= r.status_code < 300:
                result.successes += 1
            elif r.status_code == 404:
                result.successes += 1  # 404 on a flag key is expected
            else:
                result.errors += 1
            await _think(100, 500)

        return result


class ActiveBettorScenario:
    """
    Full gaming flow — the highest-traffic, most critical path:
    balance → create session → [N bets with heartbeats] → close session → history

    This scenario exercises the entire transactional stack:
    wallet reservation, risk evaluation, bet settlement.
    """

    name = "active_bettor"

    def __init__(self, bets_per_session: int = 7) -> None:
        self.bets_per_session = bets_per_session

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)
        creds = pool.get_random()
        if not creds:
            result.skipped = True
            result.skip_reason = "empty token pool"
            return result

        await pool.maybe_refresh(creds)
        token = creds.access_token
        user_id = creds.user_id

        # Pre-flight: check balance
        r = await ep.wallet_balance(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(50, 150)

        # Create game session
        r = await ep.game_session_create(client, token)
        result.requests += 1
        session_id: Optional[str] = None
        if r.status_code == 201:
            result.successes += 1
            # We can't easily get body from RequestRecord in the current design;
            # generate a plausible session_id for downstream calls and handle
            # 404s gracefully. In a full impl, client would return body too.
            session_id = None  # downstream bets will omit session_id
        else:
            result.errors += 1
        await _think(100, 300)

        # Place bets
        for i in range(self.bets_per_session):
            r = await ep.bet_place(client, token, session_id=session_id)
            result.requests += 1
            if r.status_code in (200, 201, 202):
                result.successes += 1
            elif r.status_code == 402:
                # Insufficient funds — not an error in synthetic context
                result.successes += 1
            else:
                result.errors += 1

            # Heartbeat every other bet
            if session_id and i % 2 == 1:
                await ep.game_session_heartbeat(client, token, session_id)
                result.requests += 1
                result.successes += 1
            await _think(200, 800)

        # Fetch bet history
        r = await ep.bet_history(client, token, limit=10)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(100, 300)

        # Close session if we have one
        if session_id:
            r = await ep.game_session_close(client, token, session_id)
            result.requests += 1
            result.successes += 1 if r.status_code == 200 else 0
            result.errors += 0 if r.status_code == 200 else 1

        return result


class WalletHeavyScenario:
    """
    Wallet-focused flow: deposit → check balance → transaction history
    → optional withdraw. Models payment-heavy users (cashiers, finance
    validation).
    """

    name = "wallet_heavy"

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)
        creds = pool.get_random()
        if not creds:
            result.skipped = True
            result.skip_reason = "empty token pool"
            return result

        await pool.maybe_refresh(creds)
        token = creds.access_token
        user_id = creds.user_id

        # Deposit
        r = await ep.wallet_deposit(client, token, user_id, amount="100.00")
        result.requests += 1
        result.successes += 1 if r.status_code in (200, 201) else 0
        result.errors += 0 if r.status_code in (200, 201) else 1

        # Idempotency replay test — same key, should return same result
        if r.status_code in (200, 201):
            # Re-record last idempotency key; note: in our client the
            # idem key is generated per request. For a true replay test,
            # pass the same key explicitly.
            pass
        await _think(100, 200)

        # Balance check
        r = await ep.wallet_balance(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(50, 100)

        # Transaction history (multiple pages)
        for _ in range(random.randint(1, 3)):
            r = await ep.wallet_transactions(client, token, user_id, limit=10)
            result.requests += 1
            result.successes += 1 if r.status_code == 200 else 0
            result.errors += 0 if r.status_code == 200 else 1
            await _think(80, 200)

        # Occasional withdraw
        if random.random() < 0.3:
            r = await ep.wallet_withdraw(client, token, user_id, amount="20.00")
            result.requests += 1
            result.successes += 1 if r.status_code in (200, 201, 202) else 0
            result.errors += 0 if r.status_code in (200, 201, 202) else 1

        # Risk signal after large wallet activity
        if random.random() < 0.5:
            r = await ep.risk_signal(client, token, user_id)
            result.requests += 1
            result.successes += 1 if r.status_code == 202 else 0
            result.errors += 0 if r.status_code == 202 else 1

        return result


class RegistrationFunnelScenario:
    """
    Full new-user onboarding path: register → profile → first deposit → first bet.

    Models the acquisition funnel: a fresh user signing up, making an initial
    deposit, and placing their first bet. High think times reflect form-filling
    and reading game instructions.
    """

    name = "registration_funnel"

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)

        # Register a brand-new user (needs response body for user_id / tokens)
        payload = register_payload()
        try:
            async with client._session.post(
                f"{client.base_url}/api/v1/auth/register",
                json=payload,
                headers={"Content-Type": "application/json", "X-Synthetic": "true"},
            ) as resp:
                result.requests += 1
                if resp.status == 201:
                    result.successes += 1
                    data = await resp.json()
                    user_id: str = data["user_id"]
                    token: str = data["access_token"]
                else:
                    result.errors += 1
                    await resp.read()
                    return result
        except Exception as exc:
            logger.debug("Registration exception: %s", exc)
            result.errors += 1
            return result

        await _think(300, 900)  # user reads welcome screen

        # View own profile
        r = await ep.users_profile(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(400, 1200)  # user fills out profile details

        # Check spending limits
        r = await ep.users_limits(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(200, 600)

        # Feature flags (bonus offer eligibility check)
        r = await ep.config_flags(client, token)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(100, 400)

        # First deposit — cautious amounts
        r = await ep.wallet_deposit(client, token, user_id, amount=_amt(20.0, 150.0))
        result.requests += 1
        result.successes += 1 if r.status_code in (200, 201) else 0
        result.errors += 0 if r.status_code in (200, 201) else 1
        await _think(600, 2000)  # payment processing wait / confirmation

        # Balance check after deposit
        r = await ep.wallet_balance(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(300, 700)

        # Create first game session
        r = await ep.game_session_create(client, token)
        result.requests += 1
        result.successes += 1 if r.status_code == 201 else 0
        result.errors += 0 if r.status_code == 201 else 1
        await _think(800, 2000)  # user reads game rules

        # First bet — small, cautious
        for _ in range(random.randint(1, 3)):
            r = await ep.bet_place(client, token, amount=_amt(1.0, 15.0))
            result.requests += 1
            if r.status_code in (200, 201, 202, 402):
                result.successes += 1
            else:
                result.errors += 1
            await _think(500, 1500)

        # View bet history
        r = await ep.bet_history(client, token, limit=5)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1

        return result


class HighRollerScenario:
    """
    High-value bettor: large deposits, rapid high-stake bets, risk evaluation,
    and partial withdrawals. Generates the highest monetary volume per session.

    Exercises the risk engine intensively via periodic risk signals and
    score checks. Think times are short — high rollers move fast.
    """

    name = "high_roller"

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)
        creds = pool.get_random()
        if not creds:
            result.skipped = True
            result.skip_reason = "empty token pool"
            return result

        await pool.maybe_refresh(creds)
        token = creds.access_token
        user_id = creds.user_id

        # Large deposit
        r = await ep.wallet_deposit(client, token, user_id, amount=_amt(500.0, 5000.0))
        result.requests += 1
        result.successes += 1 if r.status_code in (200, 201) else 0
        result.errors += 0 if r.status_code in (200, 201) else 1
        await _think(80, 200)

        # Pre-session risk evaluation
        r = await ep.risk_evaluate(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code in (200, 202) else 0
        result.errors += 0 if r.status_code in (200, 202) else 1
        await _think(50, 150)

        # Balance check
        r = await ep.wallet_balance(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(50, 100)

        # Create session
        r = await ep.game_session_create(client, token)
        result.requests += 1
        result.successes += 1 if r.status_code == 201 else 0
        result.errors += 0 if r.status_code == 201 else 1
        await _think(100, 300)

        # Rapid high-value bets
        bets = random.randint(10, 25)
        for i in range(bets):
            r = await ep.bet_place(client, token, amount=_amt(50.0, 1000.0))
            result.requests += 1
            if r.status_code in (200, 201, 202, 402):
                result.successes += 1
            else:
                result.errors += 1

            # Periodic velocity signal (every 5 bets)
            if i > 0 and i % 5 == 0:
                r2 = await ep.risk_signal(client, token, user_id)
                result.requests += 1
                result.successes += 1 if r2.status_code == 202 else 0
                result.errors += 0 if r2.status_code == 202 else 1

            await _think(80, 350)

        # Risk score check after heavy session
        r = await ep.risk_score(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(80, 200)

        # Transaction history — multiple pages
        for _ in range(random.randint(2, 4)):
            r = await ep.wallet_transactions(client, token, user_id, limit=25)
            result.requests += 1
            result.successes += 1 if r.status_code == 200 else 0
            result.errors += 0 if r.status_code == 200 else 1
            await _think(100, 300)

        # Partial withdrawal
        if random.random() < 0.65:
            r = await ep.wallet_withdraw(client, token, user_id, amount=_amt(200.0, 2000.0))
            result.requests += 1
            result.successes += 1 if r.status_code in (200, 201, 202) else 0
            result.errors += 0 if r.status_code in (200, 201, 202) else 1

        return result


class LiveEventBettorScenario:
    """
    In-play / live-event bettor: rapid burst of bets on a single live game.

    Simulates the traffic spike pattern during a live sports or esports event:
    many users placing many small-to-medium bets in quick succession.
    Think times are minimal — excitement drives rapid interaction.
    """

    name = "live_event_bettor"

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)
        creds = pool.get_random()
        if not creds:
            result.skipped = True
            result.skip_reason = "empty token pool"
            return result

        await pool.maybe_refresh(creds)
        token = creds.access_token
        user_id = creds.user_id

        # Quick balance check before entering the live event
        r = await ep.wallet_balance(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1
        await _think(20, 80)

        # Single live game for the whole session (mirrors real in-play behaviour)
        live_game = random.choice(LIVE_GAME_IDS)

        # Open session
        r = await ep.game_session_create(client, token, game_id=live_game)
        result.requests += 1
        session_id: Optional[str] = None
        if r.status_code == 201:
            result.successes += 1
        else:
            result.errors += 1
        await _think(30, 100)

        # Burst of rapid-fire bets — minimal think time, all on the same game
        bets = random.randint(5, 20)
        for i in range(bets):
            r = await ep.bet_place(
                client,
                token,
                session_id=session_id,
                game_id=live_game,
                amount=_amt(5.0, 150.0),
            )
            result.requests += 1
            if r.status_code in (200, 201, 202, 402):
                result.successes += 1
            else:
                result.errors += 1

            # Heartbeat every 3 bets if we have a session
            if session_id and i % 3 == 2:
                await ep.game_session_heartbeat(client, token, session_id)
                result.requests += 1
                result.successes += 1

            await _think(30, 180)  # live-event pace: much faster than normal

        # Event ends — close session
        if session_id:
            r = await ep.game_session_close(client, token, session_id)
            result.requests += 1
            result.successes += 1 if r.status_code == 200 else 0
            result.errors += 0 if r.status_code == 200 else 1

        # Review results
        r = await ep.bet_history(client, token, limit=20)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1

        # Check balance after event
        r = await ep.wallet_balance(client, token, user_id)
        result.requests += 1
        result.successes += 1 if r.status_code == 200 else 0
        result.errors += 0 if r.status_code == 200 else 1

        return result


class AdminScenario:
    """
    Internal diagnostic flow: status, config, db stats.
    Low frequency. Requires admin token — skips gracefully if unavailable.
    """

    name = "admin"

    async def run(self, client: SynthClient, pool: TokenPool) -> ScenarioResult:
        result = ScenarioResult(scenario=self.name)
        admin = pool.get_admin()
        if not admin:
            result.skipped = True
            result.skip_reason = "no admin token"
            return result

        token = admin.access_token
        for fn in [ep.admin_status, ep.admin_config, ep.admin_db_stats]:
            r = await fn(client, token)
            result.requests += 1
            if 200 <= r.status_code < 300:
                result.successes += 1
            else:
                result.errors += 1
            await _think(200, 500)

        return result


# ── Registry ──────────────────────────────────────────────────────────────────

SCENARIO_REGISTRY: dict[str, type] = {
    "anonymous": AnonymousScenario,
    "authenticated": AuthenticatedUserScenario,
    "active_bettor": ActiveBettorScenario,
    "wallet_heavy": WalletHeavyScenario,
    "admin": AdminScenario,
    "registration_funnel": RegistrationFunnelScenario,
    "high_roller": HighRollerScenario,
    "live_event_bettor": LiveEventBettorScenario,
}


def pick_scenario(weights: dict[str, float]) -> type:
    """Weighted random scenario selection."""
    names = list(weights.keys())
    wts = [weights[n] for n in names]
    chosen = random.choices(names, weights=wts, k=1)[0]
    cls = SCENARIO_REGISTRY.get(chosen, AuthenticatedUserScenario)
    return cls
