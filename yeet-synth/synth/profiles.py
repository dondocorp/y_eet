"""
Traffic profile definitions.

A profile is a named set of operational parameters that fully describes
how the runner should behave: concurrency, RPS, duration, burst characteristics,
scenario weights, and which validation modes to activate.
"""
from __future__ import annotations

from .config import ProfileConfig

PROFILES: dict[str, ProfileConfig] = {

    # ── Smoke ─────────────────────────────────────────────────────────────────
    # Fast sanity check: one pass through every major endpoint.
    "smoke": ProfileConfig(
        name="smoke",
        concurrency=5,
        duration_seconds=30,
        rps_target=5.0,
        scenario_weights={
            "anonymous": 0.20,
            "authenticated": 0.30,
            "active_bettor": 0.30,
            "wallet_heavy": 0.15,
            "admin": 0.05,
        },
    ),

    # ── Low / steady state ────────────────────────────────────────────────────
    # Simulates off-peak traffic. Good for regression checks on deploys.
    "low": ProfileConfig(
        name="low",
        concurrency=5,
        duration_seconds=120,
        rps_target=10.0,
        scenario_weights={
            "anonymous": 0.15,
            "authenticated": 0.30,
            "active_bettor": 0.35,
            "wallet_heavy": 0.15,
            "admin": 0.05,
        },
    ),

    # ── Normal production ─────────────────────────────────────────────────────
    # Representative of median-hour production traffic.
    "normal": ProfileConfig(
        name="normal",
        concurrency=20,
        duration_seconds=300,
        rps_target=50.0,
        scenario_weights={
            "anonymous": 0.10,
            "authenticated": 0.25,
            "active_bettor": 0.45,
            "wallet_heavy": 0.15,
            "admin": 0.05,
        },
    ),

    # ── Burst / spike event ───────────────────────────────────────────────────
    # Models a sports event or promotion where traffic spikes sharply.
    "burst": ProfileConfig(
        name="burst",
        concurrency=80,
        duration_seconds=180,
        rps_target=200.0,
        burst_factor=4.0,
        burst_duration_seconds=15,
        burst_interval_seconds=30,
        scenario_weights={
            "anonymous": 0.05,
            "authenticated": 0.15,
            "active_bettor": 0.65,   # bet-heavy during a match
            "wallet_heavy": 0.10,
            "admin": 0.05,
        },
    ),

    # ── Chaos / error-heavy ───────────────────────────────────────────────────
    # Injects faults alongside normal traffic.
    # Used in staging to verify error handling and alerting.
    "chaos": ProfileConfig(
        name="chaos",
        concurrency=15,
        duration_seconds=180,
        rps_target=30.0,
        chaos_enabled=True,
        scenario_weights={
            "anonymous": 0.10,
            "authenticated": 0.25,
            "active_bettor": 0.40,
            "wallet_heavy": 0.20,
            "admin": 0.05,
        },
    ),

    # ── Mesh validation ───────────────────────────────────────────────────────
    # Low traffic volume; focused on exercising Istio policies.
    "mesh": ProfileConfig(
        name="mesh",
        concurrency=10,
        duration_seconds=120,
        rps_target=20.0,
        mesh_validation=True,
        scenario_weights={
            "anonymous": 0.10,
            "authenticated": 0.30,
            "active_bettor": 0.40,
            "wallet_heavy": 0.15,
            "admin": 0.05,
        },
    ),

    # ── Canary validation ─────────────────────────────────────────────────────
    # Sends traffic specifically to verify a canary rollout percentage.
    "canary": ProfileConfig(
        name="canary",
        concurrency=10,
        duration_seconds=120,
        rps_target=25.0,
        canary_validation=True,
        mesh_validation=True,
        scenario_weights={
            "anonymous": 0.05,
            "authenticated": 0.30,
            "active_bettor": 0.40,
            "wallet_heavy": 0.20,
            "admin": 0.05,
        },
    ),
}


def get_profile(name: str) -> ProfileConfig:
    if name not in PROFILES:
        raise ValueError(
            f"Unknown profile '{name}'. Available: {', '.join(PROFILES)}"
        )
    return PROFILES[name]
