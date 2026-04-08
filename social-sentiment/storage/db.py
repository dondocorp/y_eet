"""
SQLite access layer for the social sentiment subsystem.
Intentionally lightweight — no ORM. Direct sqlite3 with typed helpers.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator

DB_PATH = Path(__file__).parent.parent / "data" / "social_sentiment.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

logger = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_run_id() -> str:
    return str(uuid.uuid4())


def _recover_corrupt_db(db_path: Path) -> None:
    """Delete a corrupt DB and its WAL/SHM sidecar files so init_db() starts fresh."""
    logger.warning("db_corrupt_detected path=%s — deleting and recreating", db_path)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
            logger.warning("db_recover_deleted path=%s", p)


def _open_connection(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    if db_path is None:
        db_path = DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        return _open_connection(db_path)
    except sqlite3.DatabaseError as exc:
        if "malformed" in str(exc).lower() or "disk image" in str(exc).lower():
            _recover_corrupt_db(db_path)
            return _open_connection(db_path)
        raise


@contextmanager
def transaction(
    db_path: Path | None = None,
) -> Generator[sqlite3.Connection, None, None]:
    if db_path is None:
        db_path = DB_PATH
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | None = None) -> None:
    if db_path is None:
        db_path = DB_PATH
    schema = SCHEMA_PATH.read_text()
    try:
        with transaction(db_path) as conn:
            conn.executescript(schema)
    except sqlite3.DatabaseError as exc:
        if "malformed" in str(exc).lower() or "disk image" in str(exc).lower():
            _recover_corrupt_db(db_path)
            with transaction(db_path) as conn:
                conn.executescript(schema)
        else:
            raise


# ── scrape_runs ─────────────────────────────────────────────────────────────


def insert_scrape_run(platform: str, query: str, run_id: str | None = None) -> str:
    rid = run_id or new_run_id()
    with transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO scrape_runs
               (run_id, platform, query, started_at, status)
               VALUES (?, ?, ?, ?, 'running')""",
            (rid, platform, query, utcnow()),
        )
    return rid


def finish_scrape_run(
    run_id: str,
    status: str,
    posts_found: int = 0,
    error_msg: str | None = None,
    duration_ms: int | None = None,
) -> None:
    with transaction() as conn:
        conn.execute(
            """UPDATE scrape_runs SET
               status=?, finished_at=?, posts_found=?, error_msg=?, duration_ms=?
               WHERE run_id=?""",
            (status, utcnow(), posts_found, error_msg, duration_ms, run_id),
        )


# ── raw_posts ───────────────────────────────────────────────────────────────


def insert_raw_posts(rows: list[dict[str, Any]]) -> int:
    """Bulk-insert raw posts. Returns number of actually inserted rows."""
    if not rows:
        return 0
    inserted = 0
    with transaction() as conn:
        for r in rows:
            cur = conn.execute(
                """INSERT OR IGNORE INTO raw_posts
                   (post_id, platform, scrape_run_id, raw_text, author_handle,
                    author_followers, post_url, posted_at, likes, reposts,
                    replies, upvotes, subreddit, language)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    r["post_id"],
                    r["platform"],
                    r["scrape_run_id"],
                    r["raw_text"],
                    r.get("author_handle"),
                    r.get("author_followers"),
                    r.get("post_url"),
                    r.get("posted_at"),
                    r.get("likes", 0),
                    r.get("reposts", 0),
                    r.get("replies", 0),
                    r.get("upvotes", 0),
                    r.get("subreddit"),
                    r.get("language", "en"),
                ),
            )
            inserted += cur.rowcount
    return inserted


def fetch_unprocessed_raw_posts(limit: int = 500) -> list[sqlite3.Row]:
    with transaction() as conn:
        return conn.execute(
            """SELECT rp.* FROM raw_posts rp
               LEFT JOIN normalized_posts np
                 ON np.platform=rp.platform AND np.post_id=rp.post_id
               WHERE np.id IS NULL
               ORDER BY rp.scraped_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()


# ── normalized_posts ────────────────────────────────────────────────────────


def insert_normalized_posts(rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    inserted = 0
    with transaction() as conn:
        for r in rows:
            cur = conn.execute(
                """INSERT OR IGNORE INTO normalized_posts
                   (raw_post_id, platform, post_id, clean_text,
                    char_count, word_count, lang_detected, posted_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (
                    r["raw_post_id"],
                    r["platform"],
                    r["post_id"],
                    r["clean_text"],
                    r.get("char_count"),
                    r.get("word_count"),
                    r.get("lang_detected"),
                    r.get("posted_at"),
                ),
            )
            inserted += cur.rowcount
    return inserted


def fetch_unclassified_posts(limit: int = 200) -> list[sqlite3.Row]:
    with transaction() as conn:
        return conn.execute(
            """SELECT np.* FROM normalized_posts np
               LEFT JOIN sentiment_results sr
                 ON sr.platform=np.platform AND sr.post_id=np.post_id
               WHERE sr.id IS NULL
               ORDER BY np.posted_at ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()


# ── sentiment_results ───────────────────────────────────────────────────────


def upsert_sentiment_results(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with transaction() as conn:
        for r in rows:
            conn.execute(
                """INSERT INTO sentiment_results
                   (normalized_post_id, platform, post_id, classifier_run_id,
                    is_relevant, relevance_score, relevance_method,
                    sentiment_label, sentiment_score,
                    sentiment_raw_pos, sentiment_raw_neu, sentiment_raw_neg,
                    derived_labels, influence_weight, posted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(platform, post_id) DO UPDATE SET
                     is_relevant=excluded.is_relevant,
                     relevance_score=excluded.relevance_score,
                     sentiment_label=excluded.sentiment_label,
                     sentiment_score=excluded.sentiment_score,
                     sentiment_raw_pos=excluded.sentiment_raw_pos,
                     sentiment_raw_neu=excluded.sentiment_raw_neu,
                     sentiment_raw_neg=excluded.sentiment_raw_neg,
                     derived_labels=excluded.derived_labels,
                     influence_weight=excluded.influence_weight,
                     classified_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')""",
                (
                    r["normalized_post_id"],
                    r["platform"],
                    r["post_id"],
                    r.get("classifier_run_id"),
                    int(r.get("is_relevant", False)),
                    r.get("relevance_score", 0.0),
                    r.get("relevance_method"),
                    r.get("sentiment_label"),
                    r.get("sentiment_score"),
                    r.get("sentiment_raw_pos"),
                    r.get("sentiment_raw_neu"),
                    r.get("sentiment_raw_neg"),
                    json.dumps(r.get("derived_labels", [])),
                    r.get("influence_weight", 1.0),
                    r.get("posted_at"),
                ),
            )


# ── hourly_aggregates ───────────────────────────────────────────────────────


def upsert_hourly_aggregate(row: dict[str, Any]) -> None:
    with transaction() as conn:
        conn.execute(
            """INSERT INTO hourly_aggregates
               (hour_bucket, platform, brand_query, total_posts, relevant_posts,
                positive_count, neutral_count, negative_count,
                avg_sentiment_score, weighted_sentiment,
                pos_ratio, neu_ratio, neg_ratio,
                top_derived_labels, avg_influence, computed_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(hour_bucket, platform, brand_query) DO UPDATE SET
                 total_posts=excluded.total_posts,
                 relevant_posts=excluded.relevant_posts,
                 positive_count=excluded.positive_count,
                 neutral_count=excluded.neutral_count,
                 negative_count=excluded.negative_count,
                 avg_sentiment_score=excluded.avg_sentiment_score,
                 weighted_sentiment=excluded.weighted_sentiment,
                 pos_ratio=excluded.pos_ratio,
                 neu_ratio=excluded.neu_ratio,
                 neg_ratio=excluded.neg_ratio,
                 top_derived_labels=excluded.top_derived_labels,
                 avg_influence=excluded.avg_influence,
                 computed_at=excluded.computed_at""",
            (
                row["hour_bucket"],
                row["platform"],
                row["brand_query"],
                row["total_posts"],
                row["relevant_posts"],
                row["positive_count"],
                row["neutral_count"],
                row["negative_count"],
                row.get("avg_sentiment_score"),
                row.get("weighted_sentiment"),
                row.get("pos_ratio"),
                row.get("neu_ratio"),
                row.get("neg_ratio"),
                json.dumps(row.get("top_derived_labels", {})),
                row.get("avg_influence"),
                row.get("computed_at", utcnow()),
            ),
        )


def fetch_hourly_aggregates(
    brand_query: str,
    platform: str = "ALL",
    hours: int = 24,
) -> list[sqlite3.Row]:
    with transaction() as conn:
        return conn.execute(
            """SELECT * FROM hourly_aggregates
               WHERE brand_query=? AND platform=?
               AND hour_bucket >= datetime('now', ? || ' hours')
               ORDER BY hour_bucket ASC""",
            (brand_query, platform, f"-{hours}"),
        ).fetchall()


# ── alert_events ────────────────────────────────────────────────────────────


def insert_alert_event(row: dict[str, Any]) -> bool:
    """Returns True if inserted (not suppressed/deduped), False if already exists."""
    with transaction() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO alert_events
               (alert_id, alert_name, severity, platform, brand_query,
                trigger_value, threshold, message, payload_json, sent_ok)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                row["alert_id"],
                row["alert_name"],
                row["severity"],
                row.get("platform"),
                row.get("brand_query"),
                row.get("trigger_value"),
                row.get("threshold"),
                row["message"],
                json.dumps(row.get("payload", {})),
                int(row.get("sent_ok", False)),
            ),
        )
        return cur.rowcount > 0


def mark_alert_sent(alert_id: str, sent_ok: bool = True) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE alert_events SET sent_ok=? WHERE alert_id=?",
            (int(sent_ok), alert_id),
        )


def purge_old_data(raw_days: int = 90, alert_days: int = 30) -> None:
    """Retention housekeeping — call daily."""
    with transaction() as conn:
        conn.execute(
            "DELETE FROM raw_posts WHERE scraped_at < datetime('now', ? || ' days')",
            (f"-{raw_days}",),
        )
        conn.execute(
            "DELETE FROM alert_events WHERE fired_at < datetime('now', ? || ' days')",
            (f"-{alert_days}",),
        )
