"""
Async concurrency engine.

Manages:
  - A token-bucket rate limiter (RPS target)
  - A semaphore-bounded pool of concurrent scenario workers
  - Burst windows (configurable factor + interval)
  - Graceful shutdown on SIGINT / duration expiry
  - Live progress reporting (stdout)
"""
from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Callable, Optional

from .client import SynthClient
from .config import ProfileConfig
from .metrics import MetricsCollector
from .scenarios import pick_scenario, ScenarioResult
from .token_manager import TokenPool

logger = logging.getLogger(__name__)


class TokenBucket:
    """
    Async token-bucket rate limiter.
    Fills at `rate` tokens/second; each acquire() consumes one token.
    Caps at `capacity` tokens (burst headroom).
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        self.rate = rate
        self.capacity = capacity or max(rate, 1.0)
        self._tokens = self.capacity
        self._last_fill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self.rate <= 0:
            return  # unlimited
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_fill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_fill = now
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
            await asyncio.sleep(0.005)


class TrafficRunner:
    """
    Main run loop.

    Spawns `concurrency` concurrent worker tasks.
    Each worker: pick a scenario → run it → repeat until stop event fires.
    """

    def __init__(
        self,
        client: SynthClient,
        pool: TokenPool,
        metrics: MetricsCollector,
        profile: ProfileConfig,
        on_scenario_done: Optional[Callable[[ScenarioResult], None]] = None,
    ) -> None:
        self._client = client
        self._pool = pool
        self._metrics = metrics
        self._profile = profile
        self._on_scenario_done = on_scenario_done
        self._stop_event = asyncio.Event()
        self._scenario_count = 0

    async def run(self) -> None:
        profile = self._profile
        rate_limiter = TokenBucket(rate=profile.rps_target)
        semaphore = asyncio.Semaphore(profile.concurrency)

        # Install SIGINT handler for graceful stop
        loop = asyncio.get_running_loop()
        try:
            loop.add_signal_handler(signal.SIGINT, self._stop_event.set)
            loop.add_signal_handler(signal.SIGTERM, self._stop_event.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows / restricted environments

        # Schedule automatic stop after duration
        async def _timeout_stopper() -> None:
            await asyncio.sleep(profile.duration_seconds)
            self._stop_event.set()

        async def _burst_manager() -> None:
            """Periodically amplifies rate_limiter during burst windows."""
            if profile.burst_factor <= 1.0:
                return
            while not self._stop_event.is_set():
                await asyncio.sleep(profile.burst_interval_seconds)
                if self._stop_event.is_set():
                    break
                logger.info(
                    "Burst window open (%.1fx for %ds)",
                    profile.burst_factor,
                    profile.burst_duration_seconds,
                )
                rate_limiter.rate = profile.rps_target * profile.burst_factor
                rate_limiter.capacity = rate_limiter.rate
                await asyncio.sleep(profile.burst_duration_seconds)
                rate_limiter.rate = profile.rps_target
                rate_limiter.capacity = max(profile.rps_target, 1.0)
                logger.info("Burst window closed")

        async def _worker() -> None:
            while not self._stop_event.is_set():
                await rate_limiter.acquire()
                async with semaphore:
                    if self._stop_event.is_set():
                        break
                    scenario_cls = pick_scenario(profile.scenario_weights)
                    try:
                        scenario = scenario_cls()
                        result = await scenario.run(self._client, self._pool)
                        self._scenario_count += 1
                        if self._on_scenario_done:
                            self._on_scenario_done(result)
                    except Exception as exc:
                        logger.debug("Scenario %s raised: %s", scenario_cls.__name__, exc)

        # Build all tasks
        worker_tasks = [asyncio.create_task(_worker()) for _ in range(profile.concurrency)]
        control_tasks = [
            asyncio.create_task(_timeout_stopper()),
            asyncio.create_task(_burst_manager()),
        ]

        # Progress logger
        async def _progress_logger() -> None:
            while not self._stop_event.is_set():
                await asyncio.sleep(10)
                snap = self._metrics.snapshot()
                total = sum(m.total for m in snap.values())
                errors = sum(m.server_error + m.timeout for m in snap.values())
                logger.info(
                    "[%ds] scenarios=%d requests=%d rps=%.1f error_rate=%.2f%% p99=%.0fms",
                    int(self._metrics.elapsed_seconds),
                    self._scenario_count,
                    total,
                    self._metrics.rps,
                    (errors / total * 100) if total > 0 else 0,
                    self._metrics.global_p99(),
                )

        control_tasks.append(asyncio.create_task(_progress_logger()))

        # Wait for stop
        await self._stop_event.wait()

        # Cancel all tasks
        for t in worker_tasks + control_tasks:
            t.cancel()
        await asyncio.gather(*worker_tasks, *control_tasks, return_exceptions=True)

        logger.info(
            "Run complete: %d scenarios, %.1f rps average",
            self._scenario_count,
            self._metrics.rps,
        )
