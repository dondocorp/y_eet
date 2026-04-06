"""
Alert Evaluator
────────────────
Evaluates aggregated hourly data and fires alerts via Telegram.
Also pushes structured alert payloads to Alertmanager for Prometheus routing.

Alert rules:
┌──────────────────────────────┬──────────┬──────────────────────────────────────────┐
│ Alert                        │ Severity │ Condition                                │
├──────────────────────────────┼──────────┼──────────────────────────────────────────┤
│ NegativeSentimentSpike       │ warning  │ neg_ratio > 0.40 in last 1h              │
│ NegativeSentimentCritical    │ critical │ neg_ratio > 0.65 in last 1h              │
│ MentionVolumeSpike           │ warning  │ mentions > 3× 7d median                  │
│ ScamConcernSpike             │ critical │ scam_concern label count > 5 in last 1h  │
│ PaymentIssueSurge            │ warning  │ payment_issue count > 10 in last 1h      │
│ ScrapeFailure                │ warning  │ scrape_run: failed, no success in 2h     │
│ NoDataAnomaly                │ warning  │ zero relevant posts in last 2h           │
└──────────────────────────────┴──────────┴──────────────────────────────────────────┘

Suppression: same alert_id suppressed for ALERT_SUPPRESSION_MINUTES.
Dedup key: f"{alert_name}:{platform}:{brand_query}:{hour_bucket_truncated}"
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from config.settings import (
    ALERT_MENTION_SPIKE_MULTIPLIER,
    ALERT_NEG_RATIO_THRESHOLD,
    ALERT_SCAM_COUNT_THRESHOLD,
    ALERT_SUPPRESSION_MINUTES,
    BRAND_QUERIES,
)
from metrics.exporter import METRICS
from observability.tracer import get_tracer
from storage.db import (
    fetch_hourly_aggregates,
    insert_alert_event,
    mark_alert_sent,
    transaction,
    utcnow,
)

from alerts.sender import send_alertmanager, send_telegram_alert

logger = logging.getLogger(__name__)
tracer = get_tracer()

PLATFORMS = ["twitter", "reddit", "ALL"]
CRITICAL_NEG_THRESHOLD = 0.65


def _dedup_key(alert_name: str, platform: str, brand_query: str) -> str:
    """Time-bucketed dedup key — suppresses repeats within suppression window."""
    bucket = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H")
    raw = f"{alert_name}:{platform}:{brand_query}:{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def _is_suppressed(alert_id: str) -> bool:
    with transaction() as conn:
        row = conn.execute(
            """SELECT fired_at FROM alert_events WHERE alert_id=?""",
            (alert_id,),
        ).fetchone()
    if not row:
        return False
    fired = datetime.fromisoformat(row["fired_at"].replace("Z", "+00:00"))
    age_minutes = (datetime.now(timezone.utc) - fired).total_seconds() / 60
    return age_minutes < ALERT_SUPPRESSION_MINUTES


def _fire(
    alert_name: str,
    severity: str,
    platform: str,
    brand_query: str,
    message: str,
    trigger_value: float,
    threshold: float,
    extra: dict | None = None,
) -> None:
    alert_id = _dedup_key(alert_name, platform, brand_query)

    if _is_suppressed(alert_id):
        logger.debug(
            "alert_suppressed", extra={"alert_id": alert_id, "alert_name": alert_name}
        )
        return

    payload = {
        "alert_id": alert_id,
        "alert_name": alert_name,
        "severity": severity,
        "platform": platform,
        "brand_query": brand_query,
        "message": message,
        "trigger_value": trigger_value,
        "threshold": threshold,
        "fired_at": utcnow(),
        **(extra or {}),
    }

    inserted = insert_alert_event(
        {
            **payload,
            "payload": payload,
        }
    )
    if not inserted:
        return  # race condition — already fired by concurrent run

    METRICS.alerts_triggered_total.labels(
        alert_name=alert_name, severity=severity
    ).inc()

    logger.warning(
        "alert_fired",
        extra={
            "alert_id": alert_id,
            "alert_name": alert_name,
            "severity": severity,
            "platform": platform,
            "trigger_value": trigger_value,
        },
    )

    # Send to Telegram
    sent = send_telegram_alert(payload)
    mark_alert_sent(alert_id, sent)

    # Push to Alertmanager for Prometheus-native routing
    send_alertmanager(payload)


# ── Alert rules ───────────────────────────────────────────────────────────────


def evaluate_sentiment_alerts(brand_query: str, platform: str) -> None:
    rows = fetch_hourly_aggregates(brand_query, platform, hours=2)
    if not rows:
        return

    last = rows[-1]
    neg_ratio = last["neg_ratio"] or 0.0
    rel_posts = last["relevant_posts"] or 0
    derived_raw = last["top_derived_labels"] or "{}"
    try:
        derived: dict = (
            json.loads(derived_raw) if isinstance(derived_raw, str) else derived_raw
        )
    except Exception:
        derived = {}

    # Negative ratio thresholds
    if neg_ratio >= CRITICAL_NEG_THRESHOLD and rel_posts >= 5:
        _fire(
            alert_name="NegativeSentimentCritical",
            severity="critical",
            platform=platform,
            brand_query=brand_query,
            message=(
                f"[CRITICAL] {brand_query.upper()} on {platform}: "
                f"Negative sentiment at {neg_ratio:.0%} "
                f"({last['negative_count']} of {rel_posts} relevant posts). "
                f"Immediate brand response may be needed."
            ),
            trigger_value=neg_ratio,
            threshold=CRITICAL_NEG_THRESHOLD,
        )
    elif neg_ratio >= ALERT_NEG_RATIO_THRESHOLD and rel_posts >= 3:
        _fire(
            alert_name="NegativeSentimentSpike",
            severity="warning",
            platform=platform,
            brand_query=brand_query,
            message=(
                f"[WARNING] {brand_query.upper()} on {platform}: "
                f"Negative sentiment elevated at {neg_ratio:.0%} "
                f"(threshold: {ALERT_NEG_RATIO_THRESHOLD:.0%})"
            ),
            trigger_value=neg_ratio,
            threshold=ALERT_NEG_RATIO_THRESHOLD,
        )

    # Scam concern spike
    scam_count = derived.get("scam_concern", 0)
    if scam_count >= ALERT_SCAM_COUNT_THRESHOLD:
        _fire(
            alert_name="ScamConcernSpike",
            severity="critical",
            platform=platform,
            brand_query=brand_query,
            message=(
                f"[CRITICAL] {brand_query.upper()} on {platform}: "
                f"{scam_count} scam/fraud-related posts in the last hour. "
                f"Trust & Safety team should review immediately."
            ),
            trigger_value=float(scam_count),
            threshold=float(ALERT_SCAM_COUNT_THRESHOLD),
        )

    # Payment issue surge
    payment_count = derived.get("payment_issue", 0)
    if payment_count >= 10:
        _fire(
            alert_name="PaymentIssueSurge",
            severity="warning",
            platform=platform,
            brand_query=brand_query,
            message=(
                f"[WARNING] {brand_query.upper()} on {platform}: "
                f"{payment_count} payment/withdrawal complaint posts in the last hour."
            ),
            trigger_value=float(payment_count),
            threshold=10.0,
        )


def evaluate_mention_spike(brand_query: str, platform: str) -> None:
    rows = fetch_hourly_aggregates(brand_query, platform, hours=24 * 7)
    if len(rows) < 4:
        return

    counts = [r["relevant_posts"] or 0 for r in rows]
    current = counts[-1]
    baseline = sorted(counts[:-1])[len(counts[:-1]) // 2]  # median

    if baseline > 0 and current >= baseline * ALERT_MENTION_SPIKE_MULTIPLIER:
        _fire(
            alert_name="MentionVolumeSpike",
            severity="warning",
            platform=platform,
            brand_query=brand_query,
            message=(
                f"[WARNING] {brand_query.upper()} on {platform}: "
                f"Mention spike detected. {current} mentions vs "
                f"median baseline {baseline} "
                f"({current / baseline:.1f}× — "
                f"threshold: {ALERT_MENTION_SPIKE_MULTIPLIER}×)"
            ),
            trigger_value=float(current),
            threshold=float(baseline * ALERT_MENTION_SPIKE_MULTIPLIER),
            extra={"baseline_median": baseline},
        )


def evaluate_no_data_anomaly(brand_query: str, platform: str) -> None:
    rows = fetch_hourly_aggregates(brand_query, platform, hours=2)
    if not rows:
        _fire(
            alert_name="NoDataAnomaly",
            severity="warning",
            platform=platform,
            brand_query=brand_query,
            message=(
                f"[WARNING] No social data for {brand_query.upper()} "
                f"on {platform} in the last 2 hours. "
                f"Scraper or ingestion pipeline may be down."
            ),
            trigger_value=0.0,
            threshold=1.0,
        )


def evaluate_scraper_health() -> None:
    with transaction() as conn:
        recent_fails = conn.execute(
            """SELECT platform, COUNT(*) as cnt FROM scrape_runs
               WHERE status='failed'
               AND started_at >= datetime('now', '-2 hours')
               GROUP BY platform""",
        ).fetchall()
        recent_ok = conn.execute(
            """SELECT platform FROM scrape_runs
               WHERE status='success'
               AND started_at >= datetime('now', '-2 hours')""",
        ).fetchall()

    ok_platforms = {r["platform"] for r in recent_ok}
    for r in recent_fails:
        if r["platform"] not in ok_platforms:
            _fire(
                alert_name="ScrapeFailure",
                severity="warning",
                platform=r["platform"],
                brand_query="system",
                message=(
                    f"[WARNING] Scraper for {r['platform']} has "
                    f"{r['cnt']} failed runs with no successes in the last 2 hours."
                ),
                trigger_value=float(r["cnt"]),
                threshold=1.0,
            )


# ── Entry point ───────────────────────────────────────────────────────────────


def run_alert_evaluation() -> None:
    with tracer.start_as_current_span("evaluate_alerts"):
        for brand_query in BRAND_QUERIES:
            for platform in PLATFORMS:
                evaluate_sentiment_alerts(brand_query, platform)
                evaluate_mention_spike(brand_query, platform)
                evaluate_no_data_anomaly(brand_query, platform)
        evaluate_scraper_health()


if __name__ == "__main__":
    import logging as _l

    _l.basicConfig(level="INFO")
    run_alert_evaluation()
