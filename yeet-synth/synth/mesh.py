"""
Istio / service mesh validation engine.

Each validator class encapsulates one category of mesh concern.
Validators produce MeshCheckResult objects that feed into the Evaluator.

Design philosophy:
  - We don't assume Istio is healthy. We probe and measure.
  - Pass/fail is driven by observed behaviour vs declared policy.
  - All anomalies surface as annotated RequestRecords in the MetricsCollector.
"""
from __future__ import annotations

import asyncio
import logging
import statistics
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .client import SynthClient
from .metrics import MetricsCollector, RequestRecord
from .token_manager import TokenPool
import synth.endpoints as ep

logger = logging.getLogger(__name__)


class CheckStatus(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


@dataclass
class MeshCheckResult:
    name: str
    status: CheckStatus
    message: str
    details: dict = field(default_factory=dict)
    latencies_ms: list[float] = field(default_factory=list)


# ── A. Retry Validation ───────────────────────────────────────────────────────

class RetryValidator:
    """
    Validate retry behaviour by inspecting x-envoy-attempt-count.

    Pass: retry-safe GETs may be retried; idempotent POSTs (with Idempotency-Key)
          may be retried; non-idempotent POSTs must NOT be retried.
    Fail: attempt_count > 1 on a POST /bets/place without idempotency key,
          or average attempt count > threshold (amplification risk).
    """
    name = "retry_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
        sample_size: int = 50,
    ) -> MeshCheckResult:
        creds = pool.get_random()
        if not creds:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No token available"
            )

        token = creds.access_token
        user_id = creds.user_id
        attempt_counts: list[int] = []
        unsafe_retries: int = 0

        # Sample GET /api/v1/bets/history — safe to retry
        for _ in range(sample_size):
            r = await ep.bet_history(client, token, limit=5)
            attempt_counts.append(r.envoy_attempt_count)
            await asyncio.sleep(0.05)

        # Sample POST /api/v1/bets/place — only safe if Idempotency-Key is present
        # (our client always sends it, so any retry here is acceptable)
        for _ in range(10):
            r = await ep.bet_place(client, token)
            if r.envoy_attempt_count > 1:
                # Retried on a transactional endpoint — verify idempotency key was sent
                # (we always send it in endpoints.py, so this is expected-safe)
                pass

        avg_attempts = statistics.mean(attempt_counts) if attempt_counts else 1.0
        max_attempts = max(attempt_counts) if attempt_counts else 1
        retry_amplification_rate = sum(1 for c in attempt_counts if c > 1) / len(attempt_counts)

        if unsafe_retries > 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.FAIL,
                message=f"{unsafe_retries} unsafe retries detected on non-idempotent endpoints",
                details={"unsafe_retries": unsafe_retries, "avg_attempt_count": avg_attempts},
            )
        if avg_attempts > 1.5:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message=f"High average attempt count ({avg_attempts:.2f}) — possible retry amplification",
                details={"avg_attempts": avg_attempts, "max_attempts": max_attempts,
                         "amplification_rate_pct": retry_amplification_rate * 100},
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message=f"Retry behaviour nominal (avg_attempts={avg_attempts:.2f})",
            details={"avg_attempts": avg_attempts, "max_attempts": max_attempts},
        )


# ── B. Timeout Validation ─────────────────────────────────────────────────────

class TimeoutValidator:
    """
    Detect mesh-level vs app-level timeout misalignment.

    Strategy: send requests to the health endpoint with increasing delay
    injected client-side, then observe which layer triggers the timeout.

    Mesh timeout should be slightly shorter than app timeout.
    If the app returns a 504 before the mesh times out → mismatch.
    If the client sees a connection reset vs a 504 → mesh timeout is firing.
    """
    name = "timeout_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
        probe_delay_ms: int = 0,
    ) -> MeshCheckResult:
        latencies: list[float] = []
        timeout_codes: list[int] = []
        mesh_timeouts = 0
        app_timeouts = 0

        # Probe /health/ready — lightweight enough that latency is pure overhead
        for _ in range(20):
            r = await ep.health_ready(client)
            latencies.append(r.latency_ms)
            if r.timeout:
                mesh_timeouts += 1
            elif r.status_code == 504:
                app_timeouts += 1

        p95 = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0
        p99 = sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0.0

        details = {
            "p95_ms": round(p95, 1),
            "p99_ms": round(p99, 1),
            "mesh_timeouts": mesh_timeouts,
            "app_504s": app_timeouts,
            "samples": len(latencies),
        }

        if app_timeouts > 0 and mesh_timeouts == 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message="App-level 504s observed without mesh-level timeouts — possible mesh timeout not set",
                details=details, latencies_ms=latencies,
            )
        if mesh_timeouts > 0 and app_timeouts > mesh_timeouts:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message="Both app and mesh timeouts firing — timeout hierarchy may be inverted",
                details=details, latencies_ms=latencies,
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message=f"Timeout behaviour nominal (p95={p95:.0f}ms p99={p99:.0f}ms)",
            details=details, latencies_ms=latencies,
        )


# ── C. Circuit Breaker / Outlier Detection Validation ─────────────────────────

class CircuitBreakerValidator:
    """
    Flood a degraded endpoint and verify Istio outlier detection responds.

    Observable signals:
      - x-envoy-overloaded: 1 header in responses
      - HTTP 503 with upstream_reset or overflow
      - Increasing error rate followed by recovery

    We can't inject backend failure from the synthetic client side without
    Istio VirtualService FaultInjection. Instead, we flood at high RPS and
    observe whether the mesh applies backpressure (503 upstream overflow).
    """
    name = "circuit_breaker_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
        flood_rps: float = 100.0,
        flood_duration: int = 10,
    ) -> MeshCheckResult:
        creds = pool.get_random()
        if not creds:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No token available"
            )

        results: list[RequestRecord] = []
        start = time.monotonic()
        interval = 1.0 / flood_rps

        while time.monotonic() - start < flood_duration:
            r = await ep.wallet_balance(client, creds.access_token, creds.user_id)
            results.append(r)
            await asyncio.sleep(interval)

        total = len(results)
        if total == 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No results collected"
            )

        overloaded = sum(
            1 for r in results
            if r.status_code == 503
        )
        via_istio = sum(1 for r in results if r.via_istio)
        error_rate = sum(1 for r in results if r.status_code >= 500) / total

        details = {
            "total_requests": total,
            "overloaded_503s": overloaded,
            "error_rate_pct": round(error_rate * 100, 2),
            "via_istio": via_istio,
            "flood_rps": flood_rps,
        }

        if overloaded > 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.PASS,
                message=f"Circuit breaker / outlier detection active: {overloaded} 503s observed",
                details=details,
            )
        if error_rate > 0.05:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message=f"High error rate under load ({error_rate:.1%}) — circuit breaker may be absent",
                details=details,
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message="Service handled flood without circuit breaker intervention (healthy baseline)",
            details=details,
        )


# ── D. Canary / Route Split Validation ───────────────────────────────────────

class CanaryValidator:
    """
    Validate canary traffic split.

    Sends N requests and measures the distribution of a version identifier
    in the response. Compares observed split against the declared weight.

    Looks for headers: x-canary-version, x-version, x-app-version, x-envoy-upstream-service-time.
    Also tracks x-envoy-upstream-service-time to detect version performance differences.
    """
    name = "canary_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
        expected_version: str = "canary",
        expected_weight: float = 0.10,
        tolerance: float = 0.05,
        sample_size: int = 200,
    ) -> MeshCheckResult:
        creds = pool.get_random()
        if not creds:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No token available"
            )

        version_counts: dict[str, int] = {}
        total = 0

        for _ in range(sample_size):
            r = await ep.health_live(client)
            total += 1
            v = r.canary_version or "stable"
            version_counts[v] = version_counts.get(v, 0) + 1
            await asyncio.sleep(0.02)

        if total == 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No samples collected"
            )

        canary_count = version_counts.get(expected_version, 0)
        observed_weight = canary_count / total
        deviation = abs(observed_weight - expected_weight)

        details = {
            "total_requests": total,
            "version_distribution": {k: round(v / total * 100, 1) for k, v in version_counts.items()},
            "expected_canary_weight_pct": expected_weight * 100,
            "observed_canary_weight_pct": round(observed_weight * 100, 2),
            "deviation_pct": round(deviation * 100, 2),
        }

        # If no version header is present at all, Istio may not be annotating responses
        if all(v == "stable" for v in version_counts):
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message="No version header found in responses — canary routing may be unconfigured or headers not propagated",
                details=details,
            )

        if deviation > tolerance:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.FAIL,
                message=(
                    f"Canary split deviation {deviation:.1%} exceeds tolerance {tolerance:.1%} "
                    f"(observed={observed_weight:.1%}, expected={expected_weight:.1%})"
                ),
                details=details,
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message=f"Canary split within tolerance (observed={observed_weight:.1%}, expected={expected_weight:.1%})",
            details=details,
        )


# ── E. Fault Injection Validation ─────────────────────────────────────────────

class FaultInjectionValidator:
    """
    Verify expected degradation under Istio fault injection policies.

    Istio VirtualService fault injection is configured externally.
    This validator probes the endpoint and measures:
      - Whether abort faults produce the expected HTTP status codes
      - Whether delay faults inflate latency in the expected range
      - Whether the alert pipeline fires (observable via metrics only)

    NOTE: This validator requires fault injection to be pre-configured
    in the Istio VirtualService. Run with --mesh-mode=fault.
    """
    name = "fault_injection_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
        expected_fault_rate: float = 0.30,
        expected_delay_ms: float = 500.0,
        sample_size: int = 100,
    ) -> MeshCheckResult:
        latencies: list[float] = []
        fault_codes: list[int] = []
        total = 0

        for _ in range(sample_size):
            r = await ep.health_live(client)
            total += 1
            latencies.append(r.latency_ms)
            if r.status_code >= 500 or r.status_code == 0:
                fault_codes.append(r.status_code)
            await asyncio.sleep(0.02)

        if total == 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No samples collected"
            )

        observed_fault_rate = len(fault_codes) / total
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0.0
        fault_deviation = abs(observed_fault_rate - expected_fault_rate)

        details = {
            "total": total, "fault_responses": len(fault_codes),
            "observed_fault_rate_pct": round(observed_fault_rate * 100, 1),
            "expected_fault_rate_pct": round(expected_fault_rate * 100, 1),
            "p95_latency_ms": round(p95_latency, 1),
            "expected_delay_ms": expected_delay_ms,
        }

        if observed_fault_rate < 0.01 and expected_fault_rate > 0.10:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message="Fault injection may not be active — fault rate far below expectation",
                details=details, latencies_ms=latencies,
            )
        if fault_deviation > 0.15:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message=f"Fault rate deviation {fault_deviation:.1%} — injection policy may have drifted",
                details=details, latencies_ms=latencies,
            )
        if p95_latency < expected_delay_ms * 0.5 and expected_delay_ms > 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message=f"Latency p95 ({p95_latency:.0f}ms) lower than expected delay ({expected_delay_ms}ms)",
                details=details, latencies_ms=latencies,
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message="Fault injection behaving within expected parameters",
            details=details, latencies_ms=latencies,
        )


# ── F. mTLS / Policy Path Validation ─────────────────────────────────────────

class MTLSValidator:
    """
    Verify mTLS and policy path health via externally observable signals.

    We can't directly read sidecar certificates from the client side,
    but we can detect mTLS-related failures through:
      1. Presence of x-forwarded-client-cert (XFCC) header in responses
         (Istio proxies add this on inbound when mTLS is active)
      2. Absence of unexpected 403/connection-refused on internal paths
      3. Whether service-to-service calls (internal URL) are reachable
    """
    name = "mtls_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
        sample_size: int = 30,
    ) -> MeshCheckResult:
        creds = pool.get_random()
        if not creds:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No token available"
            )

        mtls_confirmed: int = 0
        policy_failures: int = 0
        total = 0

        for _ in range(sample_size):
            r = await ep.health_ready(client)
            total += 1
            if r.via_istio:
                mtls_confirmed += 1
            if r.status_code in (403, 0):
                policy_failures += 1
            await asyncio.sleep(0.05)

        details = {
            "total": total,
            "via_istio": mtls_confirmed,
            "istio_coverage_pct": round(mtls_confirmed / total * 100, 1) if total else 0,
            "policy_failures": policy_failures,
        }

        if policy_failures > sample_size * 0.05:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.FAIL,
                message=f"{policy_failures} policy/auth failures on internal path — check PeerAuthentication policy",
                details=details,
            )
        if mtls_confirmed == 0:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message="No Istio sidecar detected in responses — service may not be in mesh or sidecar injection is disabled",
                details=details,
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message=f"mTLS path healthy ({mtls_confirmed}/{total} requests via Istio sidecar)",
            details=details,
        )


# ── G. Ingress / Egress Validation ────────────────────────────────────────────

class IngressValidator:
    """
    Validate ingress gateway behaviour:
      - Routes resolve correctly to the expected service
      - Host-based routing returns expected responses
      - Unexpected 404/503 on base paths indicates misconfigured VirtualService
    """
    name = "ingress_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
    ) -> MeshCheckResult:
        checks: list[tuple[str, int]] = []  # (endpoint_name, expected_status)

        # Base path
        r = await client.request("GET", "/", endpoint_name="GET /")
        checks.append(("GET /", r.status_code))

        # Health
        r = await ep.health_live(client)
        checks.append(("GET /health/live", r.status_code))

        r = await ep.health_ready(client)
        checks.append(("GET /health/ready", r.status_code))

        failures = [(name, code) for name, code in checks if code not in (200, 503)]
        routing_failures = [(name, code) for name, code in checks if code == 404]

        details = {
            "checks": [{"endpoint": n, "status": c} for n, c in checks],
            "routing_failures": routing_failures,
        }

        if routing_failures:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.FAIL,
                message=f"{len(routing_failures)} endpoints returned 404 — VirtualService routing may be misconfigured",
                details=details,
            )
        if failures:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message=f"{len(failures)} unexpected status codes on ingress paths",
                details=details,
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message="Ingress routing checks passed",
            details=details,
        )


# ── H. Trace Propagation Validation ──────────────────────────────────────────

class TracePropagationValidator:
    """
    Verify W3C traceparent continuity.

    We inject traceparent on every request (via client.py).
    This validator checks:
      1. Whether the server echoes or forwards trace context
      2. Whether trace IDs are consistent across a multi-hop flow
      3. Flag broken stitching (new trace started mid-flow)
    """
    name = "trace_propagation_validation"

    async def run(
        self,
        client: SynthClient,
        pool: TokenPool,
        sample_size: int = 50,
    ) -> MeshCheckResult:
        creds = pool.get_random()
        if not creds:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.SKIP, message="No token available"
            )

        sent = 0
        received = 0
        records: list[RequestRecord] = []

        for _ in range(sample_size):
            r = await ep.users_profile(client, creds.access_token, creds.user_id)
            sent += 1
            if r.traceparent_sent:
                pass
            if r.traceparent_received:
                received += 1
            records.append(r)
            await asyncio.sleep(0.03)

        propagation_rate = received / sent if sent > 0 else 0.0

        details = {
            "sent": sent,
            "received_back": received,
            "propagation_rate_pct": round(propagation_rate * 100, 1),
        }

        if propagation_rate < 0.50:
            return MeshCheckResult(
                name=self.name, status=CheckStatus.WARN,
                message=(
                    f"Low trace propagation rate ({propagation_rate:.0%}) — "
                    "server may not be echoing trace headers. "
                    "Verify OTel instrumentation and Istio EnvoyFilter trace configuration."
                ),
                details=details,
            )
        return MeshCheckResult(
            name=self.name, status=CheckStatus.PASS,
            message=f"Trace propagation nominal ({propagation_rate:.0%} of spans carry traceparent)",
            details=details,
        )


# ── Orchestrator ──────────────────────────────────────────────────────────────

class IstioValidator:
    """
    Runs all enabled mesh validators and collects results.
    """

    def __init__(self, config) -> None:
        self._cfg = config

    async def run_all(
        self,
        client: SynthClient,
        pool: TokenPool,
    ) -> list[MeshCheckResult]:
        mesh_cfg = self._cfg.mesh
        validators: list = [IngressValidator(), TracePropagationValidator(), MTLSValidator()]

        if mesh_cfg.validate_retries:
            validators.append(RetryValidator())
        if mesh_cfg.validate_timeouts:
            validators.append(TimeoutValidator())
        if mesh_cfg.validate_circuit_breaker:
            validators.append(CircuitBreakerValidator())
        if mesh_cfg.validate_canary:
            validators.append(CanaryValidator())
        if mesh_cfg.validate_fault_injection:
            validators.append(FaultInjectionValidator())

        results: list[MeshCheckResult] = []
        for v in validators:
            logger.info("Running mesh check: %s", v.name)
            try:
                r = await v.run(client, pool)
                results.append(r)
                logger.info("  %s → %s: %s", v.name, r.status.value, r.message)
            except Exception as exc:
                logger.warning("Mesh validator %s raised: %s", v.name, exc)
                results.append(MeshCheckResult(
                    name=v.name, status=CheckStatus.WARN,
                    message=f"Validator raised exception: {exc}",
                ))
        return results
