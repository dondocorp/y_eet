"""Tests for alert evaluator logic."""

from unittest.mock import patch


def test_fire_inserts_alert_event(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db

    with (
        patch("alerts.evaluator.send_telegram_alert", return_value=True),
        patch("alerts.evaluator.send_alertmanager", return_value=True),
    ):
        from alerts.evaluator import _fire

        _fire(
            alert_name="TestAlert",
            severity="warning",
            platform="reddit",
            brand_query="y_eet casino",
            message="Test alert message",
            trigger_value=0.5,
            threshold=0.4,
        )

    from storage.db import transaction

    with transaction(tmp_db) as conn:
        rows = conn.execute(
            "SELECT * FROM alert_events WHERE alert_name='TestAlert'"
        ).fetchall()
    assert len(rows) == 1
    assert rows[0]["severity"] == "warning"

    sdb.DB_PATH = orig


def test_suppression_prevents_duplicate_fire(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db

    call_count = {"n": 0}

    def fake_send(payload):
        call_count["n"] += 1
        return True

    with (
        patch("alerts.evaluator.send_telegram_alert", side_effect=fake_send),
        patch("alerts.evaluator.send_alertmanager", return_value=True),
        patch("config.settings.ALERT_SUPPRESSION_MINUTES", 60),
    ):
        from alerts.evaluator import _fire

        _fire("TestAlert2", "warning", "twitter", "y_eet.com", "msg", 0.5, 0.4)
        _fire("TestAlert2", "warning", "twitter", "y_eet.com", "msg", 0.5, 0.4)

    # Should only send once due to suppression
    assert call_count["n"] == 1

    sdb.DB_PATH = orig


def test_no_alert_when_below_threshold(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db

    # Seed hourly data below threshold
    from storage.db import upsert_hourly_aggregate

    upsert_hourly_aggregate(
        {
            "hour_bucket": "2024-01-15T13:00:00Z",
            "platform": "ALL",
            "brand_query": "y_eet casino",
            "total_posts": 10,
            "relevant_posts": 10,
            "positive_count": 7,
            "neutral_count": 2,
            "negative_count": 1,
            "pos_ratio": 0.7,
            "neu_ratio": 0.2,
            "neg_ratio": 0.1,
        }
    )

    with (
        patch("alerts.evaluator.send_telegram_alert") as mock_send,
        patch("alerts.evaluator.send_alertmanager"),
    ):
        from alerts.evaluator import evaluate_sentiment_alerts

        evaluate_sentiment_alerts("y_eet casino", "ALL")

    mock_send.assert_not_called()
    sdb.DB_PATH = orig


def test_metrics_incremented_on_alert(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db

    from metrics.exporter import METRICS

    before = METRICS.alerts_triggered_total.labels(
        alert_name="MetricTestAlert", severity="warning"
    )._value.get()

    with (
        patch("alerts.evaluator.send_telegram_alert", return_value=True),
        patch("alerts.evaluator.send_alertmanager", return_value=True),
    ):
        from alerts.evaluator import _fire

        _fire("MetricTestAlert", "warning", "reddit", "y_eet casino", "m", 0.5, 0.4)

    after = METRICS.alerts_triggered_total.labels(
        alert_name="MetricTestAlert", severity="warning"
    )._value.get()
    assert after == before + 1

    sdb.DB_PATH = orig
