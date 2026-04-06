"""
Realistic payload factory for all Yeet API endpoints.
Uses Faker for human-plausible data. All generated values match
the Zod schemas enforced by the API.
"""
from __future__ import annotations

import random
import string
import uuid
from typing import Any

from faker import Faker

fake = Faker()

# Known game IDs matching the platform's instant-game prefixes
GAME_IDS = [
    "game_crash_v1", "game_crash_v2",
    "game_slots_classic", "game_slots_mega", "game_slots_turbo",
    "game_roulette_eu", "game_blackjack_std",
]

BET_TYPES = ["spin", "straight", "auto_cashout", "split", "martingale"]

RISK_SIGNAL_TYPES = [
    "multiple_account_attempt", "rapid_bet_sequence", "velocity_breach",
    "unusual_withdrawal", "device_mismatch", "ip_change", "kyc_document_reuse",
]

JURISDICTIONS = ["GB", "MT", "CY", "GI", "IE", "SE"]

CURRENCIES = ["USD", "EUR"]

FLAG_KEYS = [
    "risk_eval_enabled", "instant_settlement_enabled",
    "withdrawal_kyc_gate", "new_game_engine_pct", "bonus_engine_v2",
]


def _amount(min_: float = 1.0, max_: float = 500.0) -> str:
    """Return a valid decimal amount string matching /^\d+\.\d{2}$/"""
    return f"{random.uniform(min_, max_):.2f}"


def _uuid() -> str:
    return str(uuid.uuid4())


def _device_fingerprint() -> str:
    return "".join(random.choices(string.hexdigits.lower(), k=32))


def register_payload() -> dict[str, Any]:
    username = (fake.user_name() + str(random.randint(10, 9999)))[:30]
    username = "".join(c for c in username if c.isalnum() or c == "_")[:30]
    username = username if len(username) >= 3 else username + "abc"
    return {
        "email": fake.unique.email(),
        "username": username,
        "password": fake.password(length=12, special_chars=True, digits=True),
        "jurisdiction": random.choice(JURISDICTIONS),
    }


def login_payload(email: str, password: str) -> dict[str, Any]:
    return {
        "email": email,
        "password": password,
        "device_fingerprint": _device_fingerprint(),
    }


def deposit_payload(min_: float = 10.0, max_: float = 1000.0) -> dict[str, Any]:
    return {
        "amount": _amount(min_, max_),
        "currency": random.choice(CURRENCIES),
        "payment_reference": f"PAY-{uuid.uuid4().hex[:12].upper()}",
    }


def withdraw_payload(min_: float = 5.0, max_: float = 200.0) -> dict[str, Any]:
    return {
        "amount": _amount(min_, max_),
        "currency": random.choice(CURRENCIES),
        "destination_id": f"DEST-{uuid.uuid4().hex[:8].upper()}",
    }


def place_bet_payload(
    session_id: str | None = None,
    game_id: str | None = None,
    amount_range: tuple[float, float] = (1.0, 100.0),
) -> dict[str, Any]:
    gid = game_id or random.choice(GAME_IDS)
    p: dict[str, Any] = {
        "game_id": gid,
        "amount": _amount(*amount_range),
        "currency": random.choice(CURRENCIES),
        "bet_type": random.choice(BET_TYPES),
    }
    if session_id:
        p["game_session_id"] = session_id
    if gid.startswith("game_crash"):
        p["parameters"] = {"auto_cashout": round(random.uniform(1.2, 10.0), 2)}
    elif gid.startswith("game_slots"):
        p["parameters"] = {"lines": random.choice([1, 5, 10, 20, 25])}
    return p


def create_session_payload(game_id: str | None = None) -> dict[str, Any]:
    return {
        "game_id": game_id or random.choice(GAME_IDS),
        "client_seed": uuid.uuid4().hex,
    }


def risk_signal_payload(user_id: str) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "signal_type": random.choice(RISK_SIGNAL_TYPES),
        "severity": random.choice(["low", "medium", "high", "critical"]),
        "context": {
            "source": "synth",
            "ip": fake.ipv4(),
            "device": _device_fingerprint()[:16],
        },
    }


def risk_evaluate_payload(
    user_id: str,
    session_id: str | None = None,
    action: str = "bet_place",
    amount: str | None = None,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "action": action,
        "amount": amount or _amount(1.0, 200.0),
        "session_id": session_id,
        "device_fingerprint": _device_fingerprint(),
        "ip_address": fake.ipv4(),
    }


def settle_bet_payload(multiplier: float | None = None) -> dict[str, Any]:
    m = multiplier or random.choice([0.0, 0.0, 2.0, 0.0, 5.0, 0.0, 10.0])
    return {"payout": f"{m:.2f}"}


def malformed_bet_payload() -> dict[str, Any]:
    """Intentionally broken payload for chaos/validation testing."""
    return {
        "game_id": "",            # violates min(1)
        "amount": "not-a-number", # violates regex
        "currency": "XYZ",        # not in enum
    }


def malformed_login_payload() -> dict[str, Any]:
    return {"email": "not-an-email", "password": "short"}


def stale_token() -> str:
    """Return a syntactically valid but expired JWT for auth failure testing."""
    # This is a pre-expired HS256 token (exp=0) — will always 401
    return (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiJzeW50aC10ZXN0IiwiZXhwIjoxfQ."
        "invalid-signature-for-testing"
    )
