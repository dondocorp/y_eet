"""Tests for the Prometheus metrics exposition."""
import threading
import time

import requests
import pytest

from metrics.exporter import start_metrics_server, METRICS, _REGISTRY
from prometheus_client import generate_latest


def test_metrics_registry_has_required_metrics():
    output = generate_latest(_REGISTRY).decode()
    required = [
        "social_scrape_runs_total",
        "social_scrape_failures_total",
        "social_posts_collected_total",
        "social_posts_relevant_total",
        "social_posts_irrelevant_total",
        "social_sentiment_positive_total",
        "social_sentiment_negative_total",
        "social_sentiment_neutral_total",
        "social_alerts_triggered_total",
        "social_pipeline_duration_seconds",
        "social_brand_relevance_confidence_bucket",
        "social_classifier_failures_total",
    ]
    for metric in required:
        assert metric in output, f"Missing metric: {metric}"


def test_counter_increments():
    before = METRICS.scrape_runs_total.labels(platform="test")._value.get()
    METRICS.scrape_runs_total.labels(platform="test").inc()
    after = METRICS.scrape_runs_total.labels(platform="test")._value.get()
    assert after == before + 1


def test_histogram_observation():
    METRICS.pipeline_duration.labels(stage="test").observe(5.0)
    output = generate_latest(_REGISTRY).decode()
    assert "social_pipeline_duration_seconds_bucket" in output


def test_metrics_http_server(unused_tcp_port=19999):
    """Smoke test: metrics server returns 200 with valid content."""
    import socket, time

    # Find a free port
    with socket.socket() as s:
        s.bind(("", 0))
        port = s.getsockname()[1]

    import config.settings as cfg
    orig_port = cfg.METRICS_PORT
    cfg.METRICS_PORT = port

    from metrics import exporter as me
    me._server = None  # reset singleton
    start_metrics_server()
    time.sleep(0.3)

    resp = requests.get(f"http://localhost:{port}/metrics", timeout=3)
    assert resp.status_code == 200
    assert "social_scrape_runs_total" in resp.text

    cfg.METRICS_PORT = orig_port
