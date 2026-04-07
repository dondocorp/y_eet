"""
OpenTelemetry tracing for the social sentiment subsystem.
Sends traces to the existing OTEL collector at OTEL_ENDPOINT.
Span naming mirrors the pipeline stage names expected in Tempo.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.semconv.resource import ResourceAttributes

from config.settings import OTEL_ENABLED, OTEL_ENDPOINT, OTEL_SERVICE_NAME

_tracer: trace.Tracer | None = None


def _init_tracer() -> trace.Tracer:
    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: OTEL_SERVICE_NAME,
            ResourceAttributes.SERVICE_VERSION: "1.0.0",
            "brand_monitoring": "true",
        }
    )
    provider = TracerProvider(resource=resource)

    if OTEL_ENABLED:
        exporter = OTLPSpanExporter(endpoint=OTEL_ENDPOINT, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))

    trace.set_tracer_provider(provider)
    return trace.get_tracer(OTEL_SERVICE_NAME)


def get_tracer() -> trace.Tracer:
    global _tracer
    if _tracer is None:
        _tracer = _init_tracer()
    return _tracer
