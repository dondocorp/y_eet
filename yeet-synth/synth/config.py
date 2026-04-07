"""
Config loader — supports YAML file + environment variable overrides.
Environment variables always win over YAML values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ThresholdConfig:
    max_error_rate: float = 0.02  # 2 % global error rate ceiling
    p95_latency_ms: float = 800.0  # SLO: p95 < 800 ms
    p99_latency_ms: float = 2000.0  # SLO: p99 < 2 s
    max_timeout_rate: float = 0.005  # 0.5 % timeout ceiling
    max_auth_failure_rate: float = 0.01  # 1 % auth failure ceiling
    canary_split_tolerance: float = 0.05  # ±5 % tolerance on declared canary weight
    min_trace_propagation_rate: float = 0.95  # 95 % of spans must carry traceparent
    retry_amplification_threshold: float = 1.5  # warn if avg attempts > 1.5 per request


@dataclass
class ProfileConfig:
    name: str
    concurrency: int
    duration_seconds: int
    rps_target: float  # 0 = unlimited
    burst_factor: float = 1.0  # multiplier applied during burst windows
    burst_duration_seconds: int = 10  # how long each burst lasts
    burst_interval_seconds: int = 60  # how often bursts occur
    chaos_enabled: bool = False
    mesh_validation: bool = False
    canary_validation: bool = False
    scenario_weights: dict[str, float] = field(default_factory=dict)


@dataclass
class CanaryConfig:
    header_name: str = "x-canary-version"  # response header carrying version
    expected_version: str = "canary"
    expected_weight: float = 0.10  # e.g. 10 % canary split
    split_tolerance: float = 0.05


@dataclass
class MeshConfig:
    validate_retries: bool = True
    validate_timeouts: bool = True
    validate_circuit_breaker: bool = True
    validate_canary: bool = False
    validate_fault_injection: bool = False
    validate_trace_propagation: bool = True
    validate_mtls: bool = True
    canary: CanaryConfig = field(default_factory=CanaryConfig)
    circuit_breaker_flood_rps: float = 200.0
    circuit_breaker_flood_duration: int = 10
    timeout_probe_delay_ms: int = 500  # injected delay for timeout probing
    fault_abort_pct: int = 30  # % of requests to abort in fault mode


@dataclass
class Config:
    # Target
    base_url: str = "http://localhost:8080"
    internal_base_url: str = "http://localhost:8080"

    # Identity
    service_name: str = "y_eet-synth"
    environment: str = "local"

    # Observability
    otel_endpoint: str = "http://localhost:4317"
    otel_enabled: bool = True
    prometheus_push_url: str = ""  # optional pushgateway
    log_level: str = "INFO"

    # Request behaviour
    request_timeout_seconds: float = 30.0
    connect_timeout_seconds: float = 5.0
    tls_verify: bool = True
    x_synthetic: bool = True  # adds X-Synthetic: true to every request

    # Token management
    token_pool_size: int = 20  # number of pre-seeded synthetic users
    seed_admin_user: bool = True  # seed one admin user for /_internal probes

    # Reporting
    json_report_path: str = "report.json"

    # Sub-configs
    profile: ProfileConfig = field(
        default_factory=lambda: ProfileConfig(
            name="normal",
            concurrency=20,
            duration_seconds=60,
            rps_target=50.0,
            scenario_weights={
                "anonymous": 0.10,
                "authenticated": 0.25,
                "active_bettor": 0.45,
                "wallet_heavy": 0.15,
                "admin": 0.05,
            },
        )
    )
    thresholds: ThresholdConfig = field(default_factory=ThresholdConfig)
    mesh: MeshConfig = field(default_factory=MeshConfig)

    @classmethod
    def from_yaml(cls, path: Path) -> "Config":
        with open(path) as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        cfg = cls()
        # Top-level keys
        for key in (
            "base_url",
            "internal_base_url",
            "service_name",
            "environment",
            "otel_endpoint",
            "otel_enabled",
            "log_level",
            "request_timeout_seconds",
            "connect_timeout_seconds",
            "tls_verify",
            "x_synthetic",
            "token_pool_size",
            "seed_admin_user",
            "json_report_path",
            "prometheus_push_url",
        ):
            if key in data:
                setattr(cfg, key, data[key])
        if "profile" in data:
            p = data["profile"]
            cfg.profile = ProfileConfig(
                **{
                    k: v
                    for k, v in p.items()
                    if k in ProfileConfig.__dataclass_fields__
                }
            )
        if "thresholds" in data:
            cfg.thresholds = ThresholdConfig(**data["thresholds"])
        if "mesh" in data:
            m = data["mesh"].copy()
            if "canary" in m:
                m["canary"] = CanaryConfig(**m.pop("canary"))
            cfg.mesh = MeshConfig(**m)
        return cfg

    @classmethod
    def from_env(cls, base: "Config | None" = None) -> "Config":
        """Apply environment variable overrides on top of an existing config."""
        cfg = base or cls()
        mapping = {
            "SYNTH_BASE_URL": "base_url",
            "SYNTH_INTERNAL_URL": "internal_base_url",
            "SYNTH_SERVICE_NAME": "service_name",
            "SYNTH_ENVIRONMENT": "environment",
            "SYNTH_OTEL_ENDPOINT": "otel_endpoint",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "otel_endpoint",
            "SYNTH_LOG_LEVEL": "log_level",
            "SYNTH_TLS_VERIFY": "tls_verify",
            "SYNTH_TOKEN_POOL_SIZE": "token_pool_size",
            "SYNTH_JSON_REPORT": "json_report_path",
        }
        for env_key, attr in mapping.items():
            val = os.getenv(env_key)
            if val is not None:
                current = getattr(cfg, attr)
                if isinstance(current, bool):
                    setattr(cfg, attr, val.lower() in ("1", "true", "yes"))
                elif isinstance(current, int):
                    setattr(cfg, attr, int(val))
                elif isinstance(current, float):
                    setattr(cfg, attr, float(val))
                else:
                    setattr(cfg, attr, val)
        return cfg


def load_config(yaml_path: str | None = None) -> Config:
    cfg: Config
    if yaml_path and Path(yaml_path).exists():
        cfg = Config.from_yaml(Path(yaml_path))
    else:
        cfg = Config()
    return Config.from_env(base=cfg)
