"""
Async HTTP client — the single point of truth for all outbound requests.

Every call through SynthClient:
  - injects X-Synthetic, X-Request-ID, traceparent headers
  - captures Istio/Envoy response headers (x-envoy-*, server, via)
  - records a RequestRecord to the MetricsCollector
  - honours per-request timeout + optional chaos delays
  - propagates OTel span context
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Optional

import aiohttp
from aiohttp import ClientSession, ClientTimeout, TCPConnector

from .metrics import MetricsCollector, RequestRecord
from .otel import carrier_from_response_headers, get_tracer, inject_trace_headers

logger = logging.getLogger(__name__)

# Istio sidecar sets this
_ISTIO_SERVER_MARKERS = ("istio-envoy", "envoy")


class SynthClient:
    """
    Async context-manager HTTP client.
    One instance per run; shared across all concurrent scenarios.
    """

    def __init__(
        self,
        base_url: str,
        internal_base_url: str,
        metrics: MetricsCollector,
        request_timeout: float = 30.0,
        connect_timeout: float = 5.0,
        tls_verify: bool = True,
        x_synthetic: bool = True,
        extra_chaos_delay_ms: float = 0.0,  # injected by ChaosInjector
        max_connections: int = 200,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.internal_base_url = internal_base_url.rstrip("/")
        self.metrics = metrics
        self.request_timeout = request_timeout
        self.connect_timeout = connect_timeout
        self.tls_verify = tls_verify
        self.x_synthetic = x_synthetic
        self.extra_chaos_delay_ms = extra_chaos_delay_ms
        self.max_connections = max_connections
        self._session: Optional[ClientSession] = None

    async def __aenter__(self) -> "SynthClient":
        connector = TCPConnector(
            limit=self.max_connections,
            ssl=None if self.tls_verify else False,
            enable_cleanup_closed=True,
        )
        timeout = ClientTimeout(
            total=self.request_timeout,
            connect=self.connect_timeout,
        )
        self._session = ClientSession(
            connector=connector,
            timeout=timeout,
            headers=self._base_headers(),
        )
        return self

    async def __aexit__(self, *_: Any) -> None:
        if self._session:
            await self._session.close()

    def _base_headers(self) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json"}
        if self.x_synthetic:
            h["X-Synthetic"] = "true"
        return h

    async def request(
        self,
        method: str,
        path: str,
        *,
        internal: bool = False,
        token: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        json: Optional[dict] = None,
        params: Optional[dict] = None,
        endpoint_name: Optional[str] = None,
        extra_headers: Optional[dict[str, str]] = None,
        chaos_delay_ms: float = 0.0,
    ) -> RequestRecord:
        assert self._session is not None, "SynthClient used outside context manager"

        base = self.internal_base_url if internal else self.base_url
        url = f"{base}{path}"
        ep_name = endpoint_name or f"{method} {path}"

        headers: dict[str, str] = {}
        request_id = str(uuid.uuid4())
        headers["X-Request-ID"] = request_id

        if token:
            headers["Authorization"] = f"Bearer {token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if extra_headers:
            headers.update(extra_headers)

        # OTel trace context injection
        tracer = get_tracer()
        traceparent_sent = False
        with tracer.start_as_current_span(
            ep_name,
            attributes={"http.method": method, "http.url": url, "synthetic": True},
        ) as span:
            traceparent_sent = inject_trace_headers(headers)

            # Optional chaos delay
            total_delay = chaos_delay_ms + self.extra_chaos_delay_ms
            if total_delay > 0:
                await asyncio.sleep(total_delay / 1000.0)

            start = time.monotonic()
            status_code = 0
            timed_out = False
            response_headers: dict[str, str] = {}

            try:
                async with self._session.request(
                    method,
                    url,
                    headers=headers,
                    json=json,
                    params=params,
                ) as resp:
                    status_code = resp.status
                    response_headers = carrier_from_response_headers(resp.headers)
                    try:
                        await resp.json(content_type=None)
                    except Exception:
                        await resp.text()

            except asyncio.TimeoutError:
                timed_out = True
                status_code = 0
                logger.debug("Timeout: %s %s", method, url)
            except aiohttp.ClientConnectorError as exc:
                status_code = 0
                logger.debug("Connection error: %s %s — %s", method, url, exc)
            except Exception as exc:
                status_code = 0
                logger.debug("Request error: %s %s — %s", method, url, exc)

            latency_ms = (time.monotonic() - start) * 1000.0

            # Extract Istio / Envoy headers
            attempt_count = int(response_headers.get("x-envoy-attempt-count", "1"))
            upstream_ms_raw = response_headers.get("x-envoy-upstream-service-time")
            upstream_ms = float(upstream_ms_raw) if upstream_ms_raw else None
            via_istio = any(
                m in response_headers.get("server", "") for m in _ISTIO_SERVER_MARKERS
            )

            # Canary version detection — supports multiple common patterns
            canary_version = (
                response_headers.get("x-canary-version")
                or response_headers.get("x-version")
                or response_headers.get("x-app-version")
                or ""
            )

            # Idempotency replay detection
            idempotency_replay = (
                response_headers.get("x-idempotency-replay", "").lower() == "true"
            )

            # Trace propagation — check if server echoed any trace headers back
            traceparent_received = "traceparent" in response_headers

            auth_failed = status_code in (401, 403)

            # OTel span enrichment
            span.set_attribute("http.status_code", status_code)
            span.set_attribute("http.response_latency_ms", latency_ms)
            if via_istio:
                span.set_attribute("mesh.via_istio", True)
            if attempt_count > 1:
                span.set_attribute("mesh.retry_count", attempt_count - 1)

        record = RequestRecord(
            endpoint=ep_name,
            method=method,
            status_code=status_code,
            latency_ms=latency_ms,
            retry_count=max(0, attempt_count - 1),
            idempotency_replay=idempotency_replay,
            timeout=timed_out,
            auth_failed=auth_failed,
            trace_id=request_id,
            traceparent_sent=traceparent_sent,
            traceparent_received=traceparent_received,
            canary_version=canary_version,
            envoy_upstream_ms=upstream_ms,
            envoy_attempt_count=attempt_count,
            via_istio=via_istio,
        )
        await self.metrics.record(record)
        return record
