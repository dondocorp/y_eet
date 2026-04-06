"""
OpenTelemetry SDK setup.
Must be called once at process start before any other imports that create spans.
Provides W3C TraceContext + Baggage propagation out of the box.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

_tracer = None
_propagator = None


def setup_otel(
    service_name: str,
    endpoint: str,
    environment: str = "local",
    enabled: bool = True,
) -> None:
    global _tracer, _propagator

    from opentelemetry import trace
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.propagators.composite import CompositePropagator
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
    from opentelemetry.baggage.propagation import W3CBaggagePropagator

    # Always set up propagation so we can inject/extract headers
    _propagator = CompositePropagator([
        TraceContextTextMapPropagator(),
        W3CBaggagePropagator(),
    ])
    set_global_textmap(_propagator)

    if not enabled:
        from opentelemetry.sdk.trace import TracerProvider
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name)
        return

    try:
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource, SERVICE_NAME, DEPLOYMENT_ENVIRONMENT
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        resource = Resource.create({
            SERVICE_NAME: service_name,
            DEPLOYMENT_ENVIRONMENT: environment,
            "synthetic": "true",
        })
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(service_name, schema_url="https://opentelemetry.io/schemas/1.21.0")
        logger.info("OTel tracing enabled → %s", endpoint)
    except Exception as exc:
        logger.warning("OTel setup failed (%s) — running without tracing", exc)
        from opentelemetry.sdk.trace import TracerProvider
        trace.set_tracer_provider(TracerProvider())
        _tracer = trace.get_tracer(service_name)


def get_tracer():
    """Return the configured tracer (noop if setup_otel not called yet)."""
    global _tracer
    if _tracer is None:
        from opentelemetry import trace
        _tracer = trace.get_tracer("yeet-synth")
    return _tracer


def inject_trace_headers(carrier: dict[str, str]) -> bool:
    """
    Inject W3C traceparent + tracestate into a headers dict.
    Returns True if a valid span context was injected.
    """
    from opentelemetry import trace
    from opentelemetry.propagate import inject

    inject(carrier)
    return "traceparent" in carrier


def extract_trace_context(headers: dict[str, str]):
    """Extract span context from response/request headers."""
    from opentelemetry.propagate import extract
    return extract(headers)


def carrier_from_response_headers(headers) -> dict[str, str]:
    """Normalise aiohttp CIMultiDictProxy to a plain dict for extraction."""
    return {k.lower(): v for k, v in headers.items()}
