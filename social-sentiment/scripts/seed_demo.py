"""
Demo data seeder for the Brand Intelligence dashboard.

Inserts synthetic but realistic posts directly into all pipeline tables,
bypassing the Playwright scraper and ML classifiers. Runs on startup when
the DB is empty so the dashboard always has something to show immediately.

Run manually:
  PYTHONPATH=/app python3 scripts/seed_demo.py
  PYTHONPATH=/app python3 scripts/seed_demo.py --force   # re-seed even if data exists
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.db import init_db, transaction

logger = logging.getLogger(__name__)

# ── Synthetic posts ──────────────────────────────────────────────────────────
# All contain "yeet casino" or co-occurring gambling context so they pass the
# relevance filter when the real pipeline eventually processes them too.

DEMO_POSTS = [
    # positive
    ("pos", "Just cashed out £500 from yeet casino, fastest withdrawal I've seen from any online casino tbh", "u/slotking88", 142, ["ux_praise"]),
    ("pos", "yeet casino free spins on signup actually gave me a decent win, not the usual rigged nonsense", "u/bonushunter_uk", 87, ["hype", "ux_praise"]),
    ("pos", "yeet.com casino support sorted my KYC in under an hour, impressed with the live chat", "u/casinoreview2024", 34, ["ux_praise"]),
    ("pos", "Big win on yeet casino crash game tonight x14 multiplier, going again lads", "u/cryptogambler_", 201, ["hype"]),
    ("pos", "yeet casino paid out my withdrawal same day, no delays no excuses. Solid platform", "u/withdrawal_watch", 56, ["ux_praise"]),
    ("pos", "yeet casino VIP manager actually called me back, rare to see that level of support in crypto casinos", "u/highroller_anon", 93, ["ux_praise"]),
    ("pos", "New slots on yeet casino this week are actually fire, RTP on the new one is 97%", "u/slots_addict_99", 167, ["hype"]),
    # negative
    ("neg", "yeet casino blocked my withdrawal for 3 weeks now, absolute scam. Do NOT deposit here", "u/frustrated_player1", 412, ["payment_issue", "scam_concern"]),
    ("neg", "can't login to yeet casino account since yesterday, live chat just keeps me waiting. Useless support", "u/yeet_victim_22", 178, ["login_issue", "support_complaint"]),
    ("neg", "yeet casino bonus wagering requirements are 60x, complete joke. They hide this in the small print", "u/bonusbuster_", 89, ["scam_concern"]),
    ("neg", "withdrawal still pending after 5 days at yeet casino. Nobody responds to my emails. Avoid.", "u/moneytrapped2024", 334, ["payment_issue", "support_complaint"]),
    ("neg", "yeet.com casino refused my payout claiming KYC issues when all docs were verified months ago. Stealing money", "u/rant_casino_", 523, ["payment_issue", "scam_concern"]),
    ("neg", "yeet casino account got suspended right after a big win. Coincidence? I think not. Rigged garbage", "u/winnerblocked_", 289, ["login_issue", "scam_concern"]),
    ("neg", "yeet casino deposit not showing after 2 hours, payment system is a disaster today", "u/deposit_fail_99", 67, ["payment_issue"]),
    # neutral
    ("neu", "anyone actually tried yeet casino? looking for honest reviews before I deposit", "u/casinonoob2024", 23, []),
    ("neu", "comparing yeet casino vs stake vs rollbit for crash games, which has better odds?", "u/crypto_casino_review", 45, []),
    ("neu", "yeet casino launched a new live dealer section apparently. Anyone tried it yet?", "u/live_dealer_fan", 31, []),
    ("neu", "yeet casino is running a weekend tournament, 10k prize pool for slots. Might enter", "u/tournament_grinder", 78, []),
    ("neu", "does yeet casino accept crypto deposits? Trying to avoid fiat for privacy", "u/crypto_anon_", 19, []),
    ("neu", "yeet casino rakeback deal vs other casinos — is 15% actually competitive?", "u/rakeback_chaser", 41, []),
]

SENT_LABEL_MAP = {"pos": "positive", "neu": "neutral", "neg": "negative"}
SENT_SCORE_MAP = {"pos": (0.72, 0.97), "neu": (0.55, 0.80), "neg": (0.68, 0.95)}
SUBREDDITS = ["r/gambling", "r/onlinecasino", "r/cryptocurrency", "r/casinoreviews", "r/bonushunting"]


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _bucket(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:00:00Z")


def has_data() -> bool:
    with transaction() as conn:
        count = conn.execute("SELECT COUNT(*) FROM raw_posts").fetchone()[0]
    return count > 0


def seed(force: bool = False) -> None:
    if not force and has_data():
        logger.info("seed_demo_skipped reason=data_already_exists")
        return

    logger.info("seed_demo_start posts=%d", len(DEMO_POSTS))
    now = datetime.now(timezone.utc)

    from config.settings import BRAND_QUERIES

    # Use first query for the run so it matches the dashboard's default filter
    primary_query = BRAND_QUERIES[0] if BRAND_QUERIES else "yeet casino"

    run_id = str(uuid.uuid4())
    clf_run_id = str(uuid.uuid4())

    with transaction() as conn:
        # 1. scrape_run
        conn.execute(
            """INSERT OR IGNORE INTO scrape_runs
               (run_id, platform, query, started_at, finished_at, status, posts_found, duration_ms)
               VALUES (?, 'reddit', ?, ?, ?, 'success', ?, 1200)""",
            (run_id, primary_query, _utcnow(), _utcnow(), len(DEMO_POSTS)),
        )

        # classifier_run (required by sentiment_results FK)
        conn.execute(
            """INSERT OR IGNORE INTO classifier_runs
               (run_id, scrape_run_id, classifier, model_name,
                started_at, finished_at, status, posts_processed)
               VALUES (?, ?, 'sentiment', 'demo_seeder', ?, ?, 'success', ?)""",
            (clf_run_id, run_id, _utcnow(), _utcnow(), len(DEMO_POSTS)),
        )

        for i, (sentiment_key, text, author, upvotes, labels) in enumerate(DEMO_POSTS):
            post_id = f"demo_{i:03d}_{uuid.uuid4().hex[:6]}"
            # Spread posts across the last 6 hours so charts show a trend
            hours_back = random.uniform(0, 6)
            posted_at = (now - timedelta(hours=hours_back)).strftime("%Y-%m-%dT%H:%M:%SZ")

            # 2. raw_posts
            conn.execute(
                """INSERT OR IGNORE INTO raw_posts
                   (post_id, platform, scrape_run_id, raw_text, author_handle,
                    post_url, posted_at, upvotes, subreddit, language)
                   VALUES (?, 'reddit', ?, ?, ?, ?, ?, ?, ?, 'en')""",
                (
                    post_id, run_id, text, author,
                    f"https://reddit.com/r/onlinecasino/comments/{post_id}",
                    posted_at, upvotes,
                    random.choice(SUBREDDITS),
                ),
            )
            raw_id = conn.execute(
                "SELECT id FROM raw_posts WHERE post_id=? AND platform='reddit'",
                (post_id,),
            ).fetchone()["id"]

            # 3. normalized_posts
            clean = text.strip()
            conn.execute(
                """INSERT OR IGNORE INTO normalized_posts
                   (raw_post_id, platform, post_id, clean_text,
                    char_count, word_count, posted_at)
                   VALUES (?, 'reddit', ?, ?, ?, ?, ?)""",
                (raw_id, post_id, clean, len(clean), len(clean.split()), posted_at),
            )
            norm_id = conn.execute(
                "SELECT id FROM normalized_posts WHERE post_id=? AND platform='reddit'",
                (post_id,),
            ).fetchone()["id"]

            # 4. sentiment_results — pre-assigned, no ML needed
            lo, hi = SENT_SCORE_MAP[sentiment_key]
            score = round(random.uniform(lo, hi), 4)
            rel_score = round(random.uniform(0.65, 0.97), 4)
            influence = round(min(1.0, 0.1 + upvotes / 600), 3)

            # raw scores that sum to ~1
            if sentiment_key == "pos":
                raw_pos, raw_neu, raw_neg = score, round((1 - score) * 0.7, 4), round((1 - score) * 0.3, 4)
            elif sentiment_key == "neg":
                raw_neg, raw_neu, raw_pos = score, round((1 - score) * 0.7, 4), round((1 - score) * 0.3, 4)
            else:
                raw_neu, raw_pos, raw_neg = score, round((1 - score) * 0.5, 4), round((1 - score) * 0.5, 4)

            conn.execute(
                """INSERT OR IGNORE INTO sentiment_results
                   (normalized_post_id, platform, post_id, classifier_run_id,
                    is_relevant, relevance_score, relevance_method,
                    sentiment_label, sentiment_score,
                    sentiment_raw_pos, sentiment_raw_neu, sentiment_raw_neg,
                    derived_labels, influence_weight, posted_at)
                   VALUES (?,?,?,?,1,?,'keyword',?,?,?,?,?,?,?,?)""",
                (
                    norm_id, "reddit", post_id, clf_run_id,
                    rel_score,
                    SENT_LABEL_MAP[sentiment_key], score,
                    raw_pos, raw_neu, raw_neg,
                    json.dumps(labels), influence, posted_at,
                ),
            )

    # 5. hourly_aggregates — seed the last 24 hours for the trend chart
    _seed_hourly_aggregates(now, primary_query)

    logger.info("seed_demo_complete posts=%d query=%r", len(DEMO_POSTS), primary_query)
    print(f"[seed_demo] Seeded {len(DEMO_POSTS)} demo posts for query '{primary_query}'")


def _seed_hourly_aggregates(now: datetime, brand_query: str) -> None:
    """Insert synthetic hourly aggregate rows for the last 24 hours."""
    platforms = ["reddit", "ALL"]

    for h in range(23, -1, -1):
        bucket_dt = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=h)
        bucket = _bucket(bucket_dt)

        # Vary the numbers to make the charts look realistic
        base_total = random.randint(8, 35)
        rel = random.randint(3, base_total)
        pos = random.randint(0, rel)
        neg = random.randint(0, rel - pos)
        neu = rel - pos - neg

        for platform in platforms:
            w_pos = round(random.uniform(0.3, 0.8), 4) if pos else None
            w_neg = round(random.uniform(0.3, 0.8), 4) if neg else None
            weighted = round(
                ((pos * (w_pos or 0)) - (neg * (w_neg or 0))) / max(rel, 1), 4
            ) if rel else None

            with transaction() as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO hourly_aggregates
                       (hour_bucket, platform, brand_query,
                        total_posts, relevant_posts,
                        positive_count, neutral_count, negative_count,
                        avg_sentiment_score, weighted_sentiment,
                        pos_ratio, neu_ratio, neg_ratio,
                        top_derived_labels, avg_influence, computed_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        bucket, platform, brand_query,
                        base_total if platform == "ALL" else max(1, base_total // 2),
                        rel if platform == "ALL" else max(1, rel // 2),
                        pos, neu, neg,
                        round(random.uniform(0.45, 0.75), 4),
                        weighted,
                        round(pos / rel, 4) if rel else None,
                        round(neu / rel, 4) if rel else None,
                        round(neg / rel, 4) if rel else None,
                        json.dumps({"payment_issue": random.randint(0, 3), "ux_praise": random.randint(0, 4)}),
                        round(random.uniform(0.2, 0.6), 3),
                        _utcnow(),
                    ),
                )


if __name__ == "__main__":
    import logging as _l
    _l.basicConfig(level="INFO", format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Re-seed even if data exists")
    args = parser.parse_args()

    init_db()
    seed(force=args.force)
