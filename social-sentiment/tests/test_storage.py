"""Integration tests for SQLite storage layer."""

from storage import db


def test_init_db_creates_tables(tmp_db):
    conn = db.get_connection(tmp_db)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    table_names = {t["name"] for t in tables}
    conn.close()
    required = {
        "scrape_runs",
        "raw_posts",
        "normalized_posts",
        "classifier_runs",
        "sentiment_results",
        "hourly_aggregates",
        "alert_events",
    }
    assert required.issubset(table_names)


def test_insert_and_fetch_raw_posts(tmp_db, sample_posts):
    # Insert scrape run first
    conn = db.get_connection(tmp_db)
    conn.execute(
        "INSERT INTO scrape_runs "
        "(run_id, platform, query, started_at, status) VALUES (?,?,?,?,?)",
        ("run-test-001", "reddit", "yeet casino", "2024-01-15T14:00:00Z", "running"),
    )
    conn.commit()
    conn.close()

    # Mock DB_PATH
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db
    try:
        inserted = db.insert_raw_posts(
            sample_posts,
        )
        assert inserted == 3

        # Dedup: inserting again should not increase count
        inserted2 = db.insert_raw_posts(sample_posts)
        assert inserted2 == 0
    finally:
        sdb.DB_PATH = orig


def test_insert_scrape_run(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db
    try:
        run_id = db.insert_scrape_run("reddit", "yeet casino")
        assert len(run_id) == 36  # UUID4

        db.finish_scrape_run(run_id, "success", posts_found=42, duration_ms=3000)

        conn = db.get_connection(tmp_db)
        row = conn.execute(
            "SELECT * FROM scrape_runs WHERE run_id=?", (run_id,)
        ).fetchone()
        conn.close()
        assert row["status"] == "success"
        assert row["posts_found"] == 42
    finally:
        sdb.DB_PATH = orig


def test_insert_alert_event(tmp_db):
    import storage.db as sdb

    orig = sdb.DB_PATH
    sdb.DB_PATH = tmp_db
    try:
        row = {
            "alert_id": "test-alert-001",
            "alert_name": "NegativeSentimentSpike",
            "severity": "warning",
            "platform": "reddit",
            "brand_query": "yeet casino",
            "message": "Test alert",
            "trigger_value": 0.55,
            "threshold": 0.40,
        }
        inserted = db.insert_alert_event(row)
        assert inserted is True

        # Dedup — same ID should not insert again
        inserted2 = db.insert_alert_event(row)
        assert inserted2 is False
    finally:
        sdb.DB_PATH = orig
