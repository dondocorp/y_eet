"""
Pass/fail evaluation model.

At the end of a run, the Evaluator checks all collected metrics and mesh
results against configured thresholds and produces a formal verdict.

Exit codes:
  0  — all checks passed
  1  — one or more FAIL checks
  2  — all checks passed but WARNs present
  3  — evaluation could not run (insufficient data)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .config import ThresholdConfig
from .mesh import MeshCheckResult, CheckStatus
from .metrics import MetricsCollector


class Verdict(Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class CheckResult:
    name: str
    verdict: Verdict
    message: str
    observed: Optional[float] = None
    threshold: Optional[float] = None
    unit: str = ""


@dataclass
class EvaluationResult:
    verdict: Verdict
    checks: list[CheckResult] = field(default_factory=list)
    confidence: float = 0.0       # 0-100: how many requests were sampled
    exit_code: int = 0

    def add(self, check: CheckResult) -> None:
        self.checks.append(check)

    def fails(self) -> list[CheckResult]:
        return [c for c in self.checks if c.verdict == Verdict.FAIL]

    def warns(self) -> list[CheckResult]:
        return [c for c in self.checks if c.verdict == Verdict.WARN]

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict.value,
            "exit_code": self.exit_code,
            "confidence": self.confidence,
            "checks": [
                {
                    "name": c.name,
                    "verdict": c.verdict.value,
                    "message": c.message,
                    "observed": c.observed,
                    "threshold": c.threshold,
                    "unit": c.unit,
                }
                for c in self.checks
            ],
        }


_MIN_REQUESTS_FOR_CONFIDENCE = 50


class Evaluator:

    def __init__(self, thresholds: ThresholdConfig) -> None:
        self._t = thresholds

    def evaluate(
        self,
        metrics: MetricsCollector,
        mesh_results: Optional[list[MeshCheckResult]] = None,
        chaos_results: Optional[list] = None,
    ) -> EvaluationResult:
        snap = metrics.snapshot()
        total = sum(m.total for m in snap.values())

        if total < 10:
            return EvaluationResult(
                verdict=Verdict.INSUFFICIENT_DATA,
                confidence=0.0,
                exit_code=3,
            )

        # Confidence: saturates at 1000 requests
        confidence = min(100.0, total / 10.0)
        result = EvaluationResult(verdict=Verdict.PASS, confidence=confidence)

        # ── Global error rate ────────────────────────────────────────────────
        error_rate = metrics.global_error_rate()
        result.add(CheckResult(
            name="global_error_rate",
            verdict=Verdict.FAIL if error_rate > self._t.max_error_rate else Verdict.PASS,
            message=f"Error rate {error_rate:.2%} vs threshold {self._t.max_error_rate:.2%}",
            observed=error_rate * 100,
            threshold=self._t.max_error_rate * 100,
            unit="%",
        ))

        # ── Global p99 latency ───────────────────────────────────────────────
        p99 = metrics.global_p99()
        result.add(CheckResult(
            name="global_p99_latency",
            verdict=Verdict.FAIL if p99 > self._t.p99_latency_ms else
                    Verdict.WARN if p99 > self._t.p95_latency_ms else Verdict.PASS,
            message=f"p99 latency {p99:.0f}ms vs threshold {self._t.p99_latency_ms:.0f}ms",
            observed=p99,
            threshold=self._t.p99_latency_ms,
            unit="ms",
        ))

        # ── Per-endpoint checks ──────────────────────────────────────────────
        for ep_name, em in snap.items():
            if em.total < 5:
                continue

            # Timeout rate
            if em.timeout_rate > self._t.max_timeout_rate:
                result.add(CheckResult(
                    name=f"timeout_rate:{ep_name}",
                    verdict=Verdict.WARN,
                    message=f"{ep_name}: timeout rate {em.timeout_rate:.2%} > threshold",
                    observed=em.timeout_rate * 100,
                    threshold=self._t.max_timeout_rate * 100,
                    unit="%",
                ))

            # Auth failure rate
            if em.total > 0 and em.auth_failures / em.total > self._t.max_auth_failure_rate:
                result.add(CheckResult(
                    name=f"auth_failure_rate:{ep_name}",
                    verdict=Verdict.WARN,
                    message=f"{ep_name}: auth failure rate {em.auth_failures / em.total:.2%}",
                    observed=em.auth_failures / em.total * 100,
                    threshold=self._t.max_auth_failure_rate * 100,
                    unit="%",
                ))

            # Retry amplification
            if em.avg_attempt_count > self._t.retry_amplification_threshold:
                result.add(CheckResult(
                    name=f"retry_amplification:{ep_name}",
                    verdict=Verdict.WARN,
                    message=(
                        f"{ep_name}: avg attempt count {em.avg_attempt_count:.2f} "
                        f"> threshold {self._t.retry_amplification_threshold:.1f} "
                        "(possible retry storm)"
                    ),
                    observed=em.avg_attempt_count,
                    threshold=self._t.retry_amplification_threshold,
                ))

            # Trace propagation
            if em.trace_sent > 10 and em.trace_propagation_rate < self._t.min_trace_propagation_rate:
                result.add(CheckResult(
                    name=f"trace_propagation:{ep_name}",
                    verdict=Verdict.WARN,
                    message=(
                        f"{ep_name}: trace propagation {em.trace_propagation_rate:.0%} "
                        f"< threshold {self._t.min_trace_propagation_rate:.0%}"
                    ),
                    observed=em.trace_propagation_rate * 100,
                    threshold=self._t.min_trace_propagation_rate * 100,
                    unit="%",
                ))

        # ── Mesh checks ──────────────────────────────────────────────────────
        if mesh_results:
            for mr in mesh_results:
                if mr.status == CheckStatus.SKIP:
                    continue
                result.add(CheckResult(
                    name=f"mesh:{mr.name}",
                    verdict=Verdict.FAIL if mr.status == CheckStatus.FAIL else
                            Verdict.WARN if mr.status == CheckStatus.WARN else Verdict.PASS,
                    message=mr.message,
                ))

        # ── Chaos checks ─────────────────────────────────────────────────────
        if chaos_results:
            for cr in chaos_results:
                result.add(CheckResult(
                    name=f"chaos:{cr.scenario}",
                    verdict=Verdict.PASS if cr.passed else Verdict.FAIL,
                    message=cr.note or f"Expected {cr.expected_status}, got {cr.status_code}",
                    observed=float(cr.status_code),
                    threshold=float(cr.expected_status),
                ))

        # ── Final verdict ────────────────────────────────────────────────────
        if any(c.verdict == Verdict.FAIL for c in result.checks):
            result.verdict = Verdict.FAIL
            result.exit_code = 1
        elif any(c.verdict == Verdict.WARN for c in result.checks):
            result.verdict = Verdict.WARN
            result.exit_code = 2
        else:
            result.verdict = Verdict.PASS
            result.exit_code = 0

        return result
