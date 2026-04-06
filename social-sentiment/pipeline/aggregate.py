"""
Hourly Aggregation Pipeline
──────────────────────────────
Rolls up sentiment_results into hourly_aggregates.
Runs after ingest, or independently on a cron schedule.

Aggregation formulas:
  pos_ratio   = positive_count / relevant_posts
  neg_ratio   = negative_count / relevant_posts
  neu_ratio   = neutral_count  / relevant_posts
  avg_score   = mean(sentiment_score) for relevant, non-null scored posts
  weighted    = sum(sentiment_score * influence_weight) / sum(influence_weight)
  spike       = current_hour_relevant > 3× median(last 7 days same platform)
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional

from metrics.exporter import METRICS
from observability.tracer import get_tracer
from storage.db import (
    fetch_hourly_aggregates,
    transaction,
    upsert_hourly_aggregate,
    utcnow,
)

logger = logging.getLogger(__name__)
tracer = get_tracer()

PLATFORMS = ["twitter", "reddit", "ALL"]
BRAND_QUERIES = None  # loaded from settings lazily


def _brand_queries():
    global BRAND_QUERIES
    if BRAND_QUERIES is None:
        from config.settings import BRAND_QUERIES as BQ

        BRAND_QUERIES = BQ
    return BRAND_QUERIES


def _hour_bucket(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:00:00Z")


def _current_hour_bucket() -> str:
    return _hour_bucket(datetime.now(timezone.utc))


def _prev_hour_bucket() -> str:
    return _hour_bucket(datetime.now(timezone.utc) - timedelta(hours=1))


# ── Core aggregation ─────────────────────────────────────────────────────────


def aggregate_hour(hour_bucket: str, platform: str, brand_query: str) -> Optional[dict]:
    """
    Pull sentiment_results for the given hour/platform/brand and compute stats.
    brand_query matching is done via relevance — posts are tagged at ingest time
    with the query that retrieved them (via scrape_run join).
    """
    with transaction() as conn:
        if platform == "ALL":
            rows = conn.execute(
                """SELECT sr.sentiment_label, sr.sentiment_score,
                          sr.influence_weight, sr.derived_labels,
                          sr.is_relevant, sr.platform
                   FROM sentiment_results sr
                   JOIN normalized_posts np
                     ON np.platform=sr.platform AND np.post_id=sr.post_id
                   JOIN raw_posts rp ON rp.id = np.raw_post_id
                   JOIN scrape_runs run ON run.run_id = rp.scrape_run_id
                   WHERE run.query LIKE ?
                   AND sr.posted_at >= ?
                   AND sr.posted_at <  strftime('%Y-%m-%dT%H:%M:%SZ', ?, '+1 hour')""",
                (f"%{brand_query}%", hour_bucket, hour_bucket),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT sr.sentiment_label, sr.sentiment_score,
                          sr.influence_weight, sr.derived_labels,
                          sr.is_relevant, sr.platform
                   FROM sentiment_results sr
                   JOIN normalized_posts np
                     ON np.platform=sr.platform AND np.post_id=sr.post_id
                   JOIN raw_posts rp ON rp.id = np.raw_post_id
                   JOIN scrape_runs run ON run.run_id = rp.scrape_run_id
                   WHERE run.query LIKE ?
                   AND sr.platform = ?
                   AND sr.posted_at >= ?
                   AND sr.posted_at <  strftime('%Y-%m-%dT%H:%M:%SZ', ?, '+1 hour')""",
                (f"%{brand_query}%", platform, hour_bucket, hour_bucket),
            ).fetchall()

    if not rows:
        return None

    total = len(rows)
    relevant = [r for r in rows if r["is_relevant"]]
    rel_count = len(relevant)
    pos_count = sum(1 for r in relevant if r["sentiment_label"] == "positive")
    neu_count = sum(1 for r in relevant if r["sentiment_label"] == "neutral")
    neg_count = sum(1 for r in relevant if r["sentiment_label"] == "negative")

    scored = [r for r in relevant if r["sentiment_score"] is not None]
    avg_score = (
        sum(r["sentiment_score"] for r in scored) / len(scored) if scored else None
    )

    # Influence-weighted sentiment (positive=1, neutral=0, negative=-1)
    SENT_VAL = {"positive": 1.0, "neutral": 0.0, "negative": -1.0}
    total_weight = sum(r["influence_weight"] or 1.0 for r in relevant)
    weighted = (
        sum(
            (SENT_VAL.get(r["sentiment_label"], 0.0)) * (r["influence_weight"] or 1.0)
            for r in relevant
            if r["sentiment_label"]
        )
        / total_weight
        if total_weight > 0
        else None
    )

    # Derived label counts
    label_counter: Counter = Counter()
    for r in relevant:
        try:
            labels = json.loads(r["derived_labels"] or "[]")
            label_counter.update(labels)
        except (json.JSONDecodeError, TypeError):
            pass

    return {
        "hour_bucket": hour_bucket,
        "platform": platform,
        "brand_query": brand_query,
        "total_posts": total,
        "relevant_posts": rel_count,
        "positive_count": pos_count,
        "neutral_count": neu_count,
        "negative_count": neg_count,
        "avg_sentiment_score": round(avg_score, 4) if avg_score is not None else None,
        "weighted_sentiment": round(weighted, 4) if weighted is not None else None,
        "pos_ratio": round(pos_count / rel_count, 4) if rel_count else None,
        "neu_ratio": round(neu_count / rel_count, 4) if rel_count else None,
        "neg_ratio": round(neg_count / rel_count, 4) if rel_count else None,
        "top_derived_labels": dict(label_counter.most_common(10)),
        "avg_influence": round(
            sum(r["influence_weight"] or 1.0 for r in relevant) / rel_count, 4
        )
        if rel_count
        else None,
        "computed_at": utcnow(),
    }


# ── Anomaly / spike detection ─────────────────────────────────────────────────


def detect_spikes(brand_query: str, platform: str = "ALL") -> list[dict]:
    """
    Returns a list of detected anomalies for the LAST completed hour.
    Uses 7-day median as baseline.
    """
    anomalies = []
    prev_bucket = _prev_hour_bucket()
    rows = fetch_hourly_aggregates(brand_query, platform, hours=24 * 7)

    if len(rows) < 3:
        return []

    # Mention spike
    mention_counts = [r["relevant_posts"] for r in rows[:-1]]
    current_mentions = rows[-1]["relevant_posts"] if rows else 0
    median_mentions = sorted(mention_counts)[len(mention_counts) // 2]

    from config.settings import (
        ALERT_MENTION_SPIKE_MULTIPLIER,
        ALERT_NEG_RATIO_THRESHOLD,
    )

    if (
        median_mentions > 0
        and current_mentions >= median_mentions * ALERT_MENTION_SPIKE_MULTIPLIER
    ):
        anomalies.append(
            {
                "type": "mention_spike",
                "platform": platform,
                "brand_query": brand_query,
                "current": current_mentions,
                "baseline": median_mentions,
                "multiplier": round(current_mentions / median_mentions, 2),
                "hour_bucket": prev_bucket,
            }
        )

    # Negative ratio spike
    if rows:
        last = rows[-1]
        neg_ratio = last["neg_ratio"] or 0.0
        if neg_ratio >= ALERT_NEG_RATIO_THRESHOLD:
            anomalies.append(
                {
                    "type": "negative_ratio_spike",
                    "platform": platform,
                    "brand_query": brand_query,
                    "neg_ratio": round(neg_ratio, 4),
                    "threshold": ALERT_NEG_RATIO_THRESHOLD,
                    "hour_bucket": prev_bucket,
                }
            )

    return anomalies


# ── Entry point ───────────────────────────────────────────────────────────────


def run_aggregation() -> list[dict]:
    t0 = time.time()
    results = []
    with tracer.start_as_current_span("aggregate_hourly") as span:
        span.set_attribute("hour", _prev_hour_bucket())
        for brand_query in _brand_queries():
            for platform in PLATFORMS:
                row = aggregate_hour(_prev_hour_bucket(), platform, brand_query)
                if row:
                    upsert_hourly_aggregate(row)
                    results.append(row)
                    logger.info(
                        "hourly_aggregate_computed",
                        extra={
                            "brand_query": brand_query,
                            "platform": platform,
                            "relevant": row["relevant_posts"],
                            "neg_ratio": row["neg_ratio"],
                        },
                    )
    METRICS.pipeline_duration.labels(stage="aggregate").observe(time.time() - t0)
    return results


if __name__ == "__main__":
    import logging as _l

    _l.basicConfig(level="INFO")
    from storage.db import init_db

    init_db()
    out = run_aggregation()
    print(f"Computed {len(out)} hourly aggregate(s)")
