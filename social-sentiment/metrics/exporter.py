"""
Prometheus Metrics Exporter
──────────────────────────────
Exposes /metrics on METRICS_PORT for Prometheus scraping.
All metrics are prefixed social_ to avoid collision with the main API.

Metric contract:
  social_scrape_runs_total          Counter  {platform}
  social_scrape_failures_total      Counter  {platform}
  social_posts_collected_total      Counter  {platform}
  social_posts_relevant_total       Counter  {platform}
  social_posts_irrelevant_total     Counter  {platform}
  social_sentiment_positive_total   Counter  {platform}
  social_sentiment_negative_total   Counter  {platform}
  social_sentiment_neutral_total    Counter  {platform}
  social_alerts_triggered_total     Counter  {alert_name, severity}
  social_pipeline_duration_seconds  Histogram {stage}
  social_brand_relevance_confidence Histogram (no labels)
  social_classifier_failures_total  Counter  {classifier}
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Optional

from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    CollectorRegistry,
    generate_latest,
    CONTENT_TYPE_LATEST,
    start_http_server,
)

from config.settings import METRICS_PORT, METRICS_PATH

logger = logging.getLogger(__name__)

_REGISTRY = CollectorRegistry(auto_describe=True)


@dataclass
class _MetricsBundle:
    scrape_runs_total: Counter
    scrape_failures_total: Counter
    posts_collected_total: Counter
    posts_relevant_total: Counter
    posts_irrelevant_total: Counter
    sentiment_positive_total: Counter
    sentiment_negative_total: Counter
    sentiment_neutral_total: Counter
    alerts_triggered_total: Counter
    pipeline_duration: Histogram
    brand_relevance_confidence: Histogram
    classifier_failures_total: Counter
    pipeline_last_run: Gauge


def _build_metrics(registry: CollectorRegistry) -> _MetricsBundle:
    return _MetricsBundle(
        scrape_runs_total=Counter(
            "social_scrape_runs_total",
            "Total scrape pipeline runs started",
            ["platform"],
            registry=registry,
        ),
        scrape_failures_total=Counter(
            "social_scrape_failures_total",
            "Total scrape runs that ended with an error",
            ["platform"],
            registry=registry,
        ),
        posts_collected_total=Counter(
            "social_posts_collected_total",
            "Total raw posts collected from all platforms",
            ["platform"],
            registry=registry,
        ),
        posts_relevant_total=Counter(
            "social_posts_relevant_total",
            "Total posts classified as brand-relevant",
            ["platform"],
            registry=registry,
        ),
        posts_irrelevant_total=Counter(
            "social_posts_irrelevant_total",
            "Total posts classified as brand-irrelevant (noise)",
            ["platform"],
            registry=registry,
        ),
        sentiment_positive_total=Counter(
            "social_sentiment_positive_total",
            "Total relevant posts classified as positive sentiment",
            ["platform"],
            registry=registry,
        ),
        sentiment_negative_total=Counter(
            "social_sentiment_negative_total",
            "Total relevant posts classified as negative sentiment",
            ["platform"],
            registry=registry,
        ),
        sentiment_neutral_total=Counter(
            "social_sentiment_neutral_total",
            "Total relevant posts classified as neutral sentiment",
            ["platform"],
            registry=registry,
        ),
        alerts_triggered_total=Counter(
            "social_alerts_triggered_total",
            "Total alerts fired by the sentiment alert evaluator",
            ["alert_name", "severity"],
            registry=registry,
        ),
        pipeline_duration=Histogram(
            "social_pipeline_duration_seconds",
            "End-to-end duration of pipeline stages",
            ["stage"],
            buckets=[0.5, 1, 5, 10, 30, 60, 120, 300, 600],
            registry=registry,
        ),
        brand_relevance_confidence=Histogram(
            "social_brand_relevance_confidence_bucket",
            "Distribution of relevance confidence scores",
            buckets=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
            registry=registry,
        ),
        classifier_failures_total=Counter(
            "social_classifier_failures_total",
            "Total posts where classifier returned a failure result",
            ["classifier"],
            registry=registry,
        ),
        pipeline_last_run=Gauge(
            "social_pipeline_last_run_timestamp",
            "Unix timestamp of the last successful pipeline run",
            registry=registry,
        ),
    )


METRICS = _build_metrics(_REGISTRY)


# ── HTTP server ──────────────────────────────────────────────────────────────

class _MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == METRICS_PATH or self.path == "/health":
            if self.path == "/health":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
                return
            output = generate_latest(_REGISTRY)
            self.send_response(200)
            self.send_header("Content-Type", CONTENT_TYPE_LATEST)
            self.send_header("Content-Length", str(len(output)))
            self.end_headers()
            self.wfile.write(output)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass  # suppress default access logs


_server: Optional[HTTPServer] = None
_thread: Optional[threading.Thread] = None


def start_metrics_server() -> None:
    global _server, _thread
    if _server is not None:
        return
    _server = HTTPServer(("0.0.0.0", METRICS_PORT), _MetricsHandler)
    _thread = threading.Thread(target=_server.serve_forever, daemon=True)
    _thread.start()
    logger.info(
        "metrics_server_started",
        extra={"port": METRICS_PORT, "path": METRICS_PATH},
    )
