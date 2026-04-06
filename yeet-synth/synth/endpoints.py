"""
Thin wrapper functions for every Yeet API endpoint.

Each function:
  - calls client.request() with the correct path/method/payload
  - handles idempotency key generation where required
  - returns the raw RequestRecord (callers decide what to do with errors)
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

from .client import SynthClient, RequestRecord
from .payloads import (
    deposit_payload, withdraw_payload, place_bet_payload, create_session_payload,
    risk_signal_payload, risk_evaluate_payload, settle_bet_payload,
)

# ── Auth ──────────────────────────────────────────────────────────────────────

async def auth_token(client: SynthClient, email: str, password: str) -> RequestRecord:
    return await client.request(
        "POST", "/api/v1/auth/token",
        json={"email": email, "password": password, "device_fingerprint": uuid.uuid4().hex},
        endpoint_name="POST /api/v1/auth/token",
    )


async def auth_refresh(client: SynthClient, refresh_token: str) -> RequestRecord:
    return await client.request(
        "POST", "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
        endpoint_name="POST /api/v1/auth/refresh",
    )


async def auth_revoke(client: SynthClient, token: str) -> RequestRecord:
    return await client.request(
        "POST", "/api/v1/auth/revoke",
        token=token,
        endpoint_name="POST /api/v1/auth/revoke",
    )


async def auth_session_validate(client: SynthClient, token: str) -> RequestRecord:
    return await client.request(
        "GET", "/api/v1/auth/session/validate",
        token=token,
        endpoint_name="GET /api/v1/auth/session/validate",
    )


# ── Users ─────────────────────────────────────────────────────────────────────

async def users_profile(client: SynthClient, token: str, user_id: str) -> RequestRecord:
    return await client.request(
        "GET", f"/api/v1/users/{user_id}/profile",
        token=token,
        endpoint_name="GET /api/v1/users/:id/profile",
    )


async def users_limits(client: SynthClient, token: str, user_id: str) -> RequestRecord:
    return await client.request(
        "GET", f"/api/v1/users/{user_id}/limits",
        token=token,
        endpoint_name="GET /api/v1/users/:id/limits",
    )


# ── Wallet ────────────────────────────────────────────────────────────────────

async def wallet_balance(client: SynthClient, token: str, user_id: str) -> RequestRecord:
    return await client.request(
        "GET", f"/api/v1/wallet/{user_id}/balance",
        token=token,
        endpoint_name="GET /api/v1/wallet/:id/balance",
    )


async def wallet_transactions(
    client: SynthClient, token: str, user_id: str,
    limit: int = 20, cursor: Optional[str] = None,
) -> RequestRecord:
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    return await client.request(
        "GET", f"/api/v1/wallet/{user_id}/transactions",
        token=token, params=params,
        endpoint_name="GET /api/v1/wallet/:id/transactions",
    )


async def wallet_deposit(
    client: SynthClient, token: str, user_id: str,
    amount: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> RequestRecord:
    payload = deposit_payload()
    if amount:
        payload["amount"] = amount
    return await client.request(
        "POST", f"/api/v1/wallet/{user_id}/deposit",
        token=token,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        json=payload,
        endpoint_name="POST /api/v1/wallet/:id/deposit",
    )


async def wallet_withdraw(
    client: SynthClient, token: str, user_id: str,
    amount: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> RequestRecord:
    payload = withdraw_payload()
    if amount:
        payload["amount"] = amount
    return await client.request(
        "POST", f"/api/v1/wallet/{user_id}/withdraw",
        token=token,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        json=payload,
        endpoint_name="POST /api/v1/wallet/:id/withdraw",
    )


# ── Games ─────────────────────────────────────────────────────────────────────

async def game_session_create(
    client: SynthClient, token: str, game_id: Optional[str] = None,
) -> RequestRecord:
    return await client.request(
        "POST", "/api/v1/games/sessions",
        token=token,
        idempotency_key=str(uuid.uuid4()),
        json=create_session_payload(game_id),
        endpoint_name="POST /api/v1/games/sessions",
    )


async def game_session_get(
    client: SynthClient, token: str, session_id: str,
) -> RequestRecord:
    return await client.request(
        "GET", f"/api/v1/games/sessions/{session_id}",
        token=token,
        endpoint_name="GET /api/v1/games/sessions/:id",
    )


async def game_session_heartbeat(
    client: SynthClient, token: str, session_id: str,
) -> RequestRecord:
    return await client.request(
        "POST", f"/api/v1/games/sessions/{session_id}/heartbeat",
        token=token,
        endpoint_name="POST /api/v1/games/sessions/:id/heartbeat",
    )


async def game_session_close(
    client: SynthClient, token: str, session_id: str,
) -> RequestRecord:
    return await client.request(
        "POST", f"/api/v1/games/sessions/{session_id}/close",
        token=token,
        endpoint_name="POST /api/v1/games/sessions/:id/close",
    )


# ── Bets ──────────────────────────────────────────────────────────────────────

async def bet_place(
    client: SynthClient, token: str,
    session_id: Optional[str] = None,
    game_id: Optional[str] = None,
    amount: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> RequestRecord:
    payload = place_bet_payload(session_id=session_id, game_id=game_id)
    if amount:
        payload["amount"] = amount
    return await client.request(
        "POST", "/api/v1/bets/place",
        token=token,
        idempotency_key=idempotency_key or str(uuid.uuid4()),
        json=payload,
        endpoint_name="POST /api/v1/bets/place",
    )


async def bet_get(client: SynthClient, token: str, bet_id: str) -> RequestRecord:
    return await client.request(
        "GET", f"/api/v1/bets/{bet_id}",
        token=token,
        endpoint_name="GET /api/v1/bets/:id",
    )


async def bet_history(
    client: SynthClient, token: str,
    limit: int = 20, cursor: Optional[str] = None,
) -> RequestRecord:
    params: dict[str, Any] = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    return await client.request(
        "GET", "/api/v1/bets/history",
        token=token, params=params,
        endpoint_name="GET /api/v1/bets/history",
    )


async def bet_settle(
    client: SynthClient, token: str, bet_id: str,
) -> RequestRecord:
    return await client.request(
        "POST", f"/api/v1/bets/{bet_id}/settle",
        token=token,
        json=settle_bet_payload(),
        endpoint_name="POST /api/v1/bets/:id/settle",
    )


# ── Risk ──────────────────────────────────────────────────────────────────────

async def risk_signal(
    client: SynthClient, token: str, user_id: str,
) -> RequestRecord:
    return await client.request(
        "POST", "/api/v1/risk/signals",
        token=token,
        json=risk_signal_payload(user_id),
        endpoint_name="POST /api/v1/risk/signals",
    )


async def risk_score(
    client: SynthClient, token: str, user_id: str,
) -> RequestRecord:
    return await client.request(
        "GET", f"/api/v1/risk/users/{user_id}/risk-score",
        token=token,
        endpoint_name="GET /api/v1/risk/users/:id/risk-score",
    )


async def risk_evaluate(
    client: SynthClient, token: str, user_id: str,
    session_id: Optional[str] = None,
) -> RequestRecord:
    return await client.request(
        "POST", "/api/v1/risk/evaluate",
        token=token,
        json=risk_evaluate_payload(user_id, session_id),
        endpoint_name="POST /api/v1/risk/evaluate",
    )


# ── Config / Feature Flags ────────────────────────────────────────────────────

async def config_flags(client: SynthClient, token: str) -> RequestRecord:
    return await client.request(
        "GET", "/api/v1/config/flags",
        token=token,
        endpoint_name="GET /api/v1/config/flags",
    )


async def config_flag(client: SynthClient, token: str, flag_key: str) -> RequestRecord:
    return await client.request(
        "GET", f"/api/v1/config/flags/{flag_key}",
        token=token,
        endpoint_name="GET /api/v1/config/flags/:key",
    )


# ── Health ────────────────────────────────────────────────────────────────────

async def health_live(client: SynthClient) -> RequestRecord:
    return await client.request("GET", "/health/live", endpoint_name="GET /health/live")


async def health_ready(client: SynthClient) -> RequestRecord:
    return await client.request("GET", "/health/ready", endpoint_name="GET /health/ready")


async def health_dependencies(client: SynthClient) -> RequestRecord:
    return await client.request(
        "GET", "/health/dependencies", endpoint_name="GET /health/dependencies"
    )


# ── Admin / Internal ──────────────────────────────────────────────────────────

async def admin_status(client: SynthClient, token: str) -> RequestRecord:
    return await client.request(
        "GET", "/_internal/status",
        token=token, internal=True,
        endpoint_name="GET /_internal/status",
    )


async def admin_config(client: SynthClient, token: str) -> RequestRecord:
    return await client.request(
        "GET", "/_internal/config",
        token=token, internal=True,
        endpoint_name="GET /_internal/config",
    )


async def admin_db_stats(client: SynthClient, token: str) -> RequestRecord:
    return await client.request(
        "GET", "/_internal/db/stats",
        token=token, internal=True,
        endpoint_name="GET /_internal/db/stats",
    )
