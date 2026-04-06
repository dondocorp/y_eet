"""
JWT token pool.

Manages a set of pre-seeded synthetic users with auto-refresh.
All scenarios draw tokens from this pool rather than re-authenticating
on every request, which mirrors real user session behaviour.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

from .payloads import login_payload, register_payload

logger = logging.getLogger(__name__)

# Access token expiry is 15 min (per platform config). We refresh at 80% of that.
_REFRESH_THRESHOLD_SECONDS = 12 * 60  # refresh after 12 min


@dataclass
class UserCredentials:
    user_id: str
    email: str
    password: str
    username: str
    access_token: str
    refresh_token: str
    issued_at: float = field(default_factory=time.monotonic)
    roles: list[str] = field(default_factory=lambda: ["player"])

    @property
    def needs_refresh(self) -> bool:
        return (time.monotonic() - self.issued_at) > _REFRESH_THRESHOLD_SECONDS

    @property
    def is_admin(self) -> bool:
        return "admin" in self.roles


class TokenPool:
    """
    Thread-safe / asyncio-safe token pool.

    Usage:
        pool = TokenPool(client, size=20)
        await pool.seed()
        creds = pool.get_random()
        creds = pool.get_admin()   # raises if no admin was seeded
    """

    def __init__(self, client, pool_size: int = 20, seed_admin: bool = True) -> None:
        self._client = client  # SynthClient (already entered as context manager)
        self._pool_size = pool_size
        self._seed_admin = seed_admin
        self._users: list[UserCredentials] = []
        self._admin: Optional[UserCredentials] = None
        self._lock = asyncio.Lock()
        self._seeded = False

    async def seed(self) -> None:
        """Register + login N synthetic users. Called once before traffic starts."""
        logger.info("Seeding token pool (%d users)...", self._pool_size)
        tasks = [self._create_user() for _ in range(self._pool_size)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                logger.warning("User seed failed: %s", r)
            elif r is not None:
                self._users.append(r)

        if self._seed_admin:
            # Admin users must already exist in the DB
            # (seeded by migration 002_seed.sql).
            # We log in with the known seed credentials.
            admin_creds = await self._login_existing(
                email="admin@yeet.com",
                password="Admin1234!",
            )
            if admin_creds:
                admin_creds.roles = ["admin", "player"]
                self._admin = admin_creds
                logger.info("Admin token acquired")
            else:
                logger.warning(
                    "Admin login failed — /_internal and admin-only "
                    "paths will be skipped"
                )

        self._seeded = True
        logger.info(
            "Token pool ready: %d regular users, admin=%s",
            len(self._users),
            self._admin is not None,
        )

    def get_random(self) -> Optional[UserCredentials]:
        """Return a random user from the pool (may return None if pool is empty)."""
        if not self._users:
            return None
        import random

        return random.choice(self._users)

    def get_admin(self) -> Optional[UserCredentials]:
        return self._admin

    async def maybe_refresh(self, creds: UserCredentials) -> None:
        """Refresh a specific user's token if it's approaching expiry."""
        if not creds.needs_refresh:
            return
        async with self._lock:
            if not creds.needs_refresh:
                return
            try:
                await self._client.request(
                    "POST",
                    "/api/v1/auth/refresh",
                    json={"refresh_token": creds.refresh_token},
                    endpoint_name="POST /api/v1/auth/refresh",
                )
                # We can't access the response body from RequestRecord directly;
                # use a raw request for token operations
                async with self._client._session.post(
                    f"{self._client.base_url}/api/v1/auth/refresh",
                    json={"refresh_token": creds.refresh_token},
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        creds.access_token = data["access_token"]
                        creds.issued_at = time.monotonic()
                        logger.debug("Refreshed token for %s", creds.email)
            except Exception as exc:
                logger.debug("Token refresh failed for %s: %s", creds.email, exc)

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _create_user(self) -> Optional[UserCredentials]:
        payload = register_payload()
        try:
            async with self._client._session.post(
                f"{self._client.base_url}/api/v1/auth/register",
                json=payload,
                headers={"Content-Type": "application/json", "X-Synthetic": "true"},
            ) as resp:
                if resp.status == 201:
                    data = await resp.json()
                    return UserCredentials(
                        user_id=data["user_id"],
                        email=payload["email"],
                        password=payload["password"],
                        username=data["username"],
                        access_token=data["access_token"],
                        refresh_token=data["refresh_token"],
                    )
                else:
                    text = await resp.text()
                    logger.debug("Register failed %d: %s", resp.status, text[:120])
                    return None
        except Exception as exc:
            logger.debug("Register exception: %s", exc)
            return None

    async def _login_existing(
        self, email: str, password: str
    ) -> Optional[UserCredentials]:
        try:
            async with self._client._session.post(
                f"{self._client.base_url}/api/v1/auth/token",
                json=login_payload(email, password),
                headers={"Content-Type": "application/json", "X-Synthetic": "true"},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return UserCredentials(
                        user_id=data.get("session_id", "unknown"),
                        email=email,
                        password=password,
                        username=email.split("@")[0],
                        access_token=data["access_token"],
                        refresh_token=data["refresh_token"],
                    )
                logger.debug("Login failed for %s: %d", email, resp.status)
                return None
        except Exception as exc:
            logger.debug("Login exception for %s: %s", email, exc)
            return None
