#!/usr/bin/env python3
"""
y_eet-synth — Yeet Platform synthetic traffic & service mesh validation tool

Usage:
  python main.py smoke
  python main.py run --profile normal --duration 300
  python main.py mesh --validate-all
  python main.py canary --expected-version canary --expected-weight 0.10
  python main.py chaos
  python main.py trace
  python main.py retry
"""

from __future__ import annotations

import asyncio
import logging
import sys
from typing import Optional

import click

from synth.client import SynthClient
from synth.config import load_config
from synth.evaluator import Evaluator
from synth.mesh import IstioValidator
from synth.metrics import MetricsCollector
from synth.otel import setup_otel
from synth.profiles import PROFILES, get_profile
from synth.reporter import Reporter
from synth.runner import TrafficRunner
from synth.token_manager import TokenPool


def _configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _common_options(f):
    f = click.option(
        "--config",
        "config_path",
        default=None,
        envvar="SYNTH_CONFIG",
        help="Path to YAML config file",
    )(f)
    f = click.option(
        "--base-url", default=None, envvar="SYNTH_BASE_URL", help="API base URL"
    )(f)
    f = click.option(
        "--log-level",
        default="INFO",
        type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"]),
        help="Log verbosity",
    )(f)
    f = click.option(
        "--no-tls-verify",
        is_flag=True,
        default=False,
        help="Disable TLS certificate verification",
    )(f)
    f = click.option(
        "--json-report",
        default=None,
        envvar="SYNTH_JSON_REPORT",
        help="Write JSON report to this path",
    )(f)
    return f


async def _run_traffic(
    cfg,
    profile_name: str,
    duration: Optional[int] = None,
    run_mesh: bool = False,
    run_chaos: bool = False,
) -> int:
    if duration:
        cfg.profile.duration_seconds = duration

    setup_otel(cfg.service_name, cfg.otel_endpoint, cfg.environment, cfg.otel_enabled)
    metrics = MetricsCollector()
    reporter = Reporter(cfg.profile.duration_seconds, cfg.json_report_path)

    async with SynthClient(
        base_url=cfg.base_url,
        internal_base_url=cfg.internal_base_url,
        metrics=metrics,
        request_timeout=cfg.request_timeout_seconds,
        connect_timeout=cfg.connect_timeout_seconds,
        tls_verify=cfg.tls_verify,
        x_synthetic=cfg.x_synthetic,
    ) as client:
        pool = TokenPool(
            client, pool_size=cfg.token_pool_size, seed_admin=cfg.seed_admin_user
        )
        await pool.seed()

        runner = TrafficRunner(client, pool, metrics, cfg.profile)
        reporter.start_progress()
        try:
            await runner.run()
        finally:
            reporter.stop_progress()

        mesh_results = None
        if run_mesh or cfg.profile.mesh_validation:
            click.echo("\nRunning mesh validation...")
            validator = IstioValidator(cfg)
            mesh_results = await validator.run_all(client, pool)

        chaos_results = None
        if run_chaos or cfg.profile.chaos_enabled:
            click.echo("\nRunning chaos scenarios...")
            from synth.chaos import ChaosInjector

            injector = ChaosInjector(client, pool)
            chaos_results = await injector.run_all()

        evaluation = Evaluator(cfg.thresholds).evaluate(
            metrics, mesh_results, chaos_results
        )
        reporter.print_summary(metrics, mesh_results, evaluation)
        reporter.write_json_report(metrics, mesh_results, evaluation, chaos_results)

        return evaluation.exit_code


@click.group()
def cli():
    """Yeet Platform synthetic traffic generator and service mesh validator."""
    pass


@cli.command()
@_common_options
@click.option("--url", "base_url_override", default=None, help="Override base URL")
def smoke(
    config_path, base_url_override, log_level, no_tls_verify, json_report, base_url
):
    """
    Quick smoke test: 30s, 5 rps, covers all endpoint categories.
    Returns exit 0 if healthy, 1 if failures detected.

    \b
    Example:
      python main.py smoke --base-url https://api.y_eet.com
    """
    _configure_logging(log_level)
    cfg = load_config(config_path)
    if base_url or base_url_override:
        cfg.base_url = base_url or base_url_override
    if no_tls_verify:
        cfg.tls_verify = False
    if json_report:
        cfg.json_report_path = json_report
    cfg.profile = get_profile("smoke")
    exit_code = asyncio.run(_run_traffic(cfg, "smoke"))
    sys.exit(exit_code)


@cli.command()
@_common_options
@click.option(
    "--profile",
    "profile_name",
    type=click.Choice(list(PROFILES.keys())),
    default="normal",
    show_default=True,
    help="Traffic profile to use",
)
@click.option("--duration", type=int, default=None, help="Override duration in seconds")
@click.option("--concurrency", type=int, default=None, help="Override concurrency")
@click.option(
    "--rps", type=float, default=None, help="Override RPS target (0 = unlimited)"
)
def run(
    config_path,
    profile_name,
    duration,
    concurrency,
    rps,
    log_level,
    no_tls_verify,
    json_report,
    base_url,
):
    """
    Run synthetic traffic with the specified profile.

    \b
    Examples:
      python main.py run --profile normal --duration 300
      python main.py run --profile burst --duration 180
      python main.py run --profile low --duration 600 --rps 5
    """
    _configure_logging(log_level)
    cfg = load_config(config_path)
    if base_url:
        cfg.base_url = base_url
    if no_tls_verify:
        cfg.tls_verify = False
    if json_report:
        cfg.json_report_path = json_report
    cfg.profile = get_profile(profile_name)
    if duration:
        cfg.profile.duration_seconds = duration
    if concurrency:
        cfg.profile.concurrency = concurrency
    if rps is not None:
        cfg.profile.rps_target = rps
    exit_code = asyncio.run(_run_traffic(cfg, profile_name))
    sys.exit(exit_code)


@cli.command()
@_common_options
@click.option(
    "--validate-all",
    is_flag=True,
    default=False,
    help="Enable all mesh validation checks",
)
@click.option("--duration", type=int, default=120)
def mesh(
    config_path, validate_all, duration, log_level, no_tls_verify, json_report, base_url
):
    """
    Istio / service mesh validation mode.

    Runs targeted validation scenarios for retry, timeout, circuit breaker,
    mTLS, trace propagation, and ingress routing.

    \b
    Example:
      python main.py mesh --validate-all --duration 120
    """
    _configure_logging(log_level)
    cfg = load_config(config_path)
    if base_url:
        cfg.base_url = base_url
    if no_tls_verify:
        cfg.tls_verify = False
    if json_report:
        cfg.json_report_path = json_report
    if validate_all:
        cfg.mesh.validate_retries = True
        cfg.mesh.validate_timeouts = True
        cfg.mesh.validate_circuit_breaker = True
        cfg.mesh.validate_canary = False  # requires active canary deployment
        cfg.mesh.validate_fault_injection = False  # requires VirtualService config
        cfg.mesh.validate_trace_propagation = True
        cfg.mesh.validate_mtls = True
    cfg.profile = get_profile("mesh")
    cfg.profile.duration_seconds = duration
    exit_code = asyncio.run(_run_traffic(cfg, "mesh", run_mesh=True))
    sys.exit(exit_code)


@cli.command()
@_common_options
@click.option(
    "--expected-version",
    default="canary",
    show_default=True,
    help="Expected value in the version response header",
)
@click.option(
    "--expected-weight",
    type=float,
    default=0.10,
    show_default=True,
    help="Expected canary traffic fraction (0.10 = 10%%)",
)
@click.option(
    "--tolerance",
    type=float,
    default=0.05,
    show_default=True,
    help="Acceptable deviation from expected weight",
)
@click.option("--sample-size", type=int, default=300, show_default=True)
@click.option("--duration", type=int, default=120, show_default=True)
def canary(
    config_path,
    expected_version,
    expected_weight,
    tolerance,
    sample_size,
    duration,
    log_level,
    no_tls_verify,
    json_report,
    base_url,
):
    """
    Canary rollout validation: verify traffic split matches declared weight.

    \b
    Example:
      python main.py canary --expected-version v2.1.0 --expected-weight 0.20
    """
    _configure_logging(log_level)
    cfg = load_config(config_path)
    if base_url:
        cfg.base_url = base_url
    if no_tls_verify:
        cfg.tls_verify = False
    if json_report:
        cfg.json_report_path = json_report
    cfg.mesh.validate_canary = True
    cfg.mesh.canary.expected_version = expected_version
    cfg.mesh.canary.expected_weight = expected_weight
    cfg.mesh.canary.split_tolerance = tolerance
    cfg.profile = get_profile("canary")
    cfg.profile.duration_seconds = duration
    exit_code = asyncio.run(_run_traffic(cfg, "canary", run_mesh=True))
    sys.exit(exit_code)


@cli.command()
@_common_options
@click.option("--duration", type=int, default=180, show_default=True)
def chaos(config_path, duration, log_level, no_tls_verify, json_report, base_url):
    """
    Chaos / fault-path validation mode.

    Runs malformed payloads, stale tokens, duplicate replays, rate limit triggers,
    and missing idempotency key scenarios alongside normal traffic.

    \b
    WARNING: Only run in staging or controlled environments.

    Example:
      python main.py chaos --duration 180
    """
    _configure_logging(log_level)
    cfg = load_config(config_path)
    if base_url:
        cfg.base_url = base_url
    if no_tls_verify:
        cfg.tls_verify = False
    if json_report:
        cfg.json_report_path = json_report
    cfg.profile = get_profile("chaos")
    cfg.profile.duration_seconds = duration
    exit_code = asyncio.run(_run_traffic(cfg, "chaos", run_chaos=True))
    sys.exit(exit_code)


@cli.command()
@_common_options
@click.option("--sample-size", type=int, default=100, show_default=True)
def trace(config_path, sample_size, log_level, no_tls_verify, json_report, base_url):
    """
    Trace propagation validation: verify W3C traceparent continuity.

    \b
    Example:
      python main.py trace --sample-size 200
    """
    _configure_logging(log_level)
    cfg = load_config(config_path)
    if base_url:
        cfg.base_url = base_url
    if no_tls_verify:
        cfg.tls_verify = False
    if json_report:
        cfg.json_report_path = json_report
    cfg.mesh.validate_trace_propagation = True
    cfg.profile = get_profile("smoke")
    cfg.profile.duration_seconds = max(30, sample_size // 5)
    exit_code = asyncio.run(_run_traffic(cfg, "smoke", run_mesh=True))
    sys.exit(exit_code)


@cli.command()
@_common_options
@click.option("--duration", type=int, default=60, show_default=True)
def retry(config_path, duration, log_level, no_tls_verify, json_report, base_url):
    """
    Retry and timeout verification: check retry behaviour and timeout alignment.

    \b
    Example:
      python main.py retry --duration 60
    """
    _configure_logging(log_level)
    cfg = load_config(config_path)
    if base_url:
        cfg.base_url = base_url
    if no_tls_verify:
        cfg.tls_verify = False
    if json_report:
        cfg.json_report_path = json_report
    cfg.mesh.validate_retries = True
    cfg.mesh.validate_timeouts = True
    cfg.profile = get_profile("mesh")
    cfg.profile.duration_seconds = duration
    exit_code = asyncio.run(_run_traffic(cfg, "mesh", run_mesh=True))
    sys.exit(exit_code)


@cli.command(name="list-profiles")
def list_profiles():
    """List all available traffic profiles."""
    for name, p in PROFILES.items():
        click.echo(
            f"  {name:<12} concurrency={p.concurrency:<4} "
            f"rps={p.rps_target:<8.1f} duration={p.duration_seconds}s"
        )


if __name__ == "__main__":
    cli()
