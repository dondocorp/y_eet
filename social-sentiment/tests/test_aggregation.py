"""Tests for the hourly aggregation pipeline."""

import json

import pytest

from pipeline.aggregate import aggregate_hour


def _seed_sentiment_data(db_path, posts: list[dict]) -> None:
    """Utility to seed normalized + classified data for aggregation tests."""
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = db_path
    try:
        from storage.db import transaction

        with transaction(db_path) as conn:
            conn.execute(
                "INSERT OR IGNORE INTO scrape_runs "
                "(run_id, platform, query, started_at, status) "
                "VALUES ('agg-run-001','reddit','y_eet casino',"
                "'2024-01-15T14:00:00Z','success')"
            )
            for p in posts:
                conn.execute(
                    "INSERT OR IGNORE INTO raw_posts "
                    "(post_id,platform,scrape_run_id,raw_text,posted_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        p["post_id"],
                        p["platform"],
                        "agg-run-001",
                        p["text"],
                        p["posted_at"],
                    ),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO normalized_posts "
                    "(raw_post_id, platform, post_id, clean_text, posted_at) "
                    "SELECT id,platform,post_id,raw_text,posted_at FROM raw_posts "
                    "WHERE post_id=? AND platform=?",
                    (p["post_id"], p["platform"]),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO sentiment_results "
                    "(normalized_post_id, platform, post_id, is_relevant, "
                    " relevance_score, sentiment_label, sentiment_score, "
                    " influence_weight, derived_labels, posted_at) "
                    "SELECT np.id, np.platform, np.post_id, "
                    "?, ?, ?, ?, ?, ?, np.posted_at "
                    "FROM normalized_posts np "
                    "WHERE np.post_id=? AND np.platform=?",
                    (
                        int(p.get("is_relevant", True)),
                        p.get("relevance_score", 0.9),
                        p.get("label", "positive"),
                        p.get("score", 0.8),
                        p.get("influence", 1.0),
                        json.dumps(p.get("derived_labels", [])),
                        p["post_id"],
                        p["platform"],
                    ),
                )
    finally:
        sdb.DB_PATH = orig


def test_aggregate_basic(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db

    posts = [
        {
            "post_id": "a1",
            "platform": "reddit",
            "text": "love y_eet casino",
            "posted_at": "2024-01-15T14:30:00Z",
            "label": "positive",
            "score": 0.9,
        },
        {
            "post_id": "a2",
            "platform": "reddit",
            "text": "y_eet casino scam",
            "posted_at": "2024-01-15T14:45:00Z",
            "label": "negative",
            "score": 0.85,
            "derived_labels": ["scam_concern"],
        },
        {
            "post_id": "a3",
            "platform": "reddit",
            "text": "ok y_eet casino ok",
            "posted_at": "2024-01-15T14:50:00Z",
            "label": "neutral",
            "score": 0.6,
        },
    ]
    try:
        _seed_sentiment_data(tmp_db, posts)
        result = aggregate_hour("2024-01-15T14:00:00Z", "ALL", "y_eet casino")
        assert result is not None
        assert result["total_posts"] == 3
        assert result["positive_count"] == 1
        assert result["negative_count"] == 1
        assert result["neutral_count"] == 1
        assert result["neg_ratio"] == pytest.approx(1 / 3, abs=0.01)
    finally:
        sdb.DB_PATH = orig


def test_aggregate_empty_hour(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db
    try:
        result = aggregate_hour("2020-01-01T00:00:00Z", "ALL", "y_eet casino")
        assert result is None
    finally:
        sdb.DB_PATH = orig


def test_aggregate_derived_label_counts(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db
    posts = [
        {
            "post_id": f"b{i}",
            "platform": "twitter",
            "text": f"post {i}",
            "posted_at": "2024-01-15T14:30:00Z",
            "label": "negative",
            "derived_labels": ["payment_issue"],
        }
        for i in range(5)
    ]
    try:
        _seed_sentiment_data(tmp_db, posts)
        result = aggregate_hour("2024-01-15T14:00:00Z", "twitter", "y_eet casino")
        assert result is not None
        labels = result["top_derived_labels"]
        if isinstance(labels, str):
            labels = json.loads(labels)
        assert labels.get("payment_issue", 0) == 5
    finally:
        sdb.DB_PATH = orig
