"""
In-process metrics collection.
Thread/coroutine-safe counters and latency histograms that produce
p50/p95/p99 without external dependencies.
"""

from __future__ import annotations

import asyncio
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RequestRecord:
    endpoint: str
    method: str
    status_code: int
    latency_ms: float
    retry_count: int = 0  # x-envoy-attempt-count - 1
    idempotency_replay: bool = False
    timeout: bool = False
    auth_failed: bool = False
    trace_id: str = ""
    traceparent_sent: bool = False
    traceparent_received: bool = False
    canary_version: str = ""  # value of x-canary-version (or equivalent)
    envoy_upstream_ms: Optional[float] = None  # x-envoy-upstream-service-time
    envoy_attempt_count: int = 1  # x-envoy-attempt-count
    via_istio: bool = False  # server: istio-envoy


@dataclass
class LatencyStats:
    samples: list[float] = field(default_factory=list)

    def record(self, ms: float) -> None:
        self.samples.append(ms)

    def percentile(self, pct: float) -> float:
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = int(len(sorted_samples) * pct / 100)
        idx = min(idx, len(sorted_samples) - 1)
        return sorted_samples[idx]

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def p99(self) -> float:
        return self.percentile(99)

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples) if self.samples else 0.0

    @property
    def count(self) -> int:
        return len(self.samples)


class EndpointMetrics:
    def __init__(self, endpoint: str) -> None:
        self.endpoint = endpoint
        self.latency = LatencyStats()
        self.total: int = 0
        self.success: int = 0  # 2xx
        self.client_error: int = 0  # 4xx
        self.server_error: int = 0  # 5xx
        self.timeout: int = 0
        self.retried: int = 0  # requests where attempt_count > 1
        self.retry_total: int = 0  # sum of extra attempts
        self.idempotency_hits: int = 0
        self.auth_failures: int = 0
        self.status_codes: dict[int, int] = defaultdict(int)
        self.canary_hits: dict[str, int] = defaultdict(int)
        self.trace_sent: int = 0
        self.trace_received: int = 0
        self.via_istio: int = 0

    def record(self, r: RequestRecord) -> None:
        self.total += 1
        self.latency.record(r.latency_ms)
        self.status_codes[r.status_code] += 1

        if 200 <= r.status_code < 300:
            self.success += 1
        elif 400 <= r.status_code < 500:
            self.client_error += 1
            if r.auth_failed:
                self.auth_failures += 1
        elif r.status_code >= 500:
            self.server_error += 1

        if r.timeout:
            self.timeout += 1
        if r.idempotency_replay:
            self.idempotency_hits += 1
        if r.envoy_attempt_count > 1:
            self.retried += 1
            self.retry_total += r.envoy_attempt_count - 1
        if r.canary_version:
            self.canary_hits[r.canary_version] += 1
        if r.traceparent_sent:
            self.trace_sent += 1
        if r.traceparent_received:
            self.trace_received += 1
        if r.via_istio:
            self.via_istio += 1

    @property
    def error_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return (self.client_error + self.server_error + self.timeout) / self.total

    @property
    def success_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.success / self.total

    @property
    def timeout_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.timeout / self.total

    @property
    def avg_attempt_count(self) -> float:
        if self.total == 0:
            return 1.0
        return 1.0 + (self.retry_total / self.total)

    @property
    def trace_propagation_rate(self) -> float:
        if self.trace_sent == 0:
            return 0.0
        return self.trace_received / self.trace_sent


class MetricsCollector:
    """Global in-process metrics store. All methods are asyncio-safe."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._endpoints: dict[str, EndpointMetrics] = {}
        self._start_time: float = time.monotonic()
        self._total_records: int = 0

    async def record(self, r: RequestRecord) -> None:
        async with self._lock:
            if r.endpoint not in self._endpoints:
                self._endpoints[r.endpoint] = EndpointMetrics(r.endpoint)
            self._endpoints[r.endpoint].record(r)
            self._total_records += 1

    @property
    def elapsed_seconds(self) -> float:
        return time.monotonic() - self._start_time

    @property
    def rps(self) -> float:
        elapsed = self.elapsed_seconds
        return self._total_records / elapsed if elapsed > 0 else 0.0

    def snapshot(self) -> dict[str, EndpointMetrics]:
        return dict(self._endpoints)

    def total(self) -> int:
        return self._total_records

    def global_error_rate(self) -> float:
        snap = self.snapshot()
        total = sum(m.total for m in snap.values())
        errors = sum(m.client_error + m.server_error + m.timeout for m in snap.values())
        return errors / total if total > 0 else 0.0

    def global_p99(self) -> float:
        all_samples: list[float] = []
        for m in self.snapshot().values():
            all_samples.extend(m.latency.samples)
        if not all_samples:
            return 0.0
        s = sorted(all_samples)
        return s[int(len(s) * 0.99)]
