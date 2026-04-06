"""
Ingestion Pipeline
──────────────────
Orchestrates:
  1. Scrape per-platform
  2. Normalize + deduplicate
  3. Relevance classify
  4. Sentiment classify
  5. Persist results

Designed to run as a cron job or via `python -m pipeline.ingest`.
Emits OTEL spans for every stage. Exposes prometheus counters via metrics module.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from config.settings import (
    BRAND_QUERIES,
    SCRAPER_ENABLED_PLATFORMS,
    SCRAPER_MAX_POSTS_PER_RUN,
)
from storage import db
from storage.db import (
    finish_scrape_run,
    insert_normalized_posts,
    insert_raw_posts,
    insert_scrape_run,
    upsert_sentiment_results,
    new_run_id,
)
from nlp.relevance import BrandRelevanceClassifier
from nlp.sentiment import SentimentClassifier
from metrics.exporter import METRICS
from observability.tracer import get_tracer

logger = logging.getLogger(__name__)
tracer = get_tracer()

_relevance_clf: Optional[BrandRelevanceClassifier] = None
_sentiment_clf: Optional[SentimentClassifier] = None


def _get_relevance() -> BrandRelevanceClassifier:
    global _relevance_clf
    if _relevance_clf is None:
        _relevance_clf = BrandRelevanceClassifier()
    return _relevance_clf


def _get_sentiment() -> SentimentClassifier:
    global _sentiment_clf
    if _sentiment_clf is None:
        _sentiment_clf = SentimentClassifier.get()
        _sentiment_clf.load()
    return _sentiment_clf


# ── Normalisation ────────────────────────────────────────────────────────────

STRIP_RE  = re.compile(r"https?://\S+|@\w+|#")
SPACE_RE  = re.compile(r"\s+")
EMOJI_RE  = re.compile(
    "[\U00010000-\U0010ffff]", flags=re.UNICODE
)  # keep BMP emoji


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = STRIP_RE.sub(" ", text)
    text = SPACE_RE.sub(" ", text).strip()
    return text[:2000]  # hard cap


def estimate_influence(post_row) -> float:
    """Simple influence score 0–1 based on engagement."""
    likes   = post_row.get("likes", 0) or 0
    reposts = post_row.get("reposts", 0) or 0
    upvotes = post_row.get("upvotes", 0) or 0
    followers = post_row.get("author_followers", 0) or 0

    engagement = likes + reposts * 2 + upvotes
    follower_boost = min(followers / 10_000, 1.0)
    raw = min(engagement / 500, 1.0) * 0.7 + follower_boost * 0.3
    return round(max(0.1, min(1.0, raw)), 3)


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_ingest_pipeline() -> dict:
    t0 = time.time()
    summary = {
        "scraped": 0, "inserted": 0, "relevant": 0,
        "positive": 0, "neutral": 0, "negative": 0,
        "errors": [],
    }

    with tracer.start_as_current_span("ingest_pipeline") as span:
        span.set_attribute("brand_queries", str(BRAND_QUERIES))
        span.set_attribute("platforms", str(SCRAPER_ENABLED_PLATFORMS))

        # ── 1. Scrape ────────────────────────────────────────────────────────
        for platform in SCRAPER_ENABLED_PLATFORMS:
            for query in BRAND_QUERIES:
                run_id = insert_scrape_run(platform, query)
                METRICS.scrape_runs_total.labels(platform=platform).inc()
                t1 = time.time()

                with tracer.start_as_current_span("scrape_run") as s_span:
                    s_span.set_attribute("platform", platform)
                    s_span.set_attribute("query", query)
                    s_span.set_attribute("run_id", run_id)
                    try:
                        scraper = _get_scraper(platform)
                        async with scraper as s:
                            result = await s.scrape_all(
                                query, max_posts=SCRAPER_MAX_POSTS_PER_RUN
                            )

                        posts = result.posts
                        METRICS.posts_collected_total.labels(platform=platform).inc(len(posts))
                        summary["scraped"] += len(posts)

                        if result.error:
                            METRICS.scrape_failures_total.labels(platform=platform).inc()
                            summary["errors"].append(
                                f"{platform}/{query}: {result.error}"
                            )

                        # Persist raw
                        raw_rows = [
                            {
                                "post_id":    p.post_id,
                                "platform":   p.platform,
                                "scrape_run_id": run_id,
                                "raw_text":   p.raw_text,
                                "author_handle": p.author_handle,
                                "author_followers": p.author_followers,
                                "post_url":   p.post_url,
                                "posted_at":  p.posted_at,
                                "likes":      p.likes,
                                "reposts":    p.reposts,
                                "replies":    p.replies,
                                "upvotes":    p.upvotes,
                                "subreddit":  p.subreddit,
                                "language":   p.language,
                            }
                            for p in posts
                        ]
                        inserted = insert_raw_posts(raw_rows)
                        summary["inserted"] += inserted
                        dur_ms = int((time.time() - t1) * 1000)
                        finish_scrape_run(
                            run_id,
                            "success" if not result.error else "failed",
                            posts_found=len(posts),
                            error_msg=result.error,
                            duration_ms=dur_ms,
                        )
                        METRICS.pipeline_duration.labels(stage="scrape").observe(
                            dur_ms / 1000
                        )
                        logger.info(
                            "scrape_run_complete",
                            extra={
                                "run_id": run_id, "platform": platform,
                                "query": query, "posts": len(posts),
                                "inserted": inserted, "duration_ms": dur_ms,
                            },
                        )
                    except Exception as exc:
                        METRICS.scrape_failures_total.labels(platform=platform).inc()
                        finish_scrape_run(run_id, "failed", error_msg=str(exc))
                        summary["errors"].append(f"scrape_{platform}: {exc}")
                        logger.error(
                            "scrape_run_error",
                            extra={"run_id": run_id, "platform": platform, "error": str(exc)},
                        )

        # ── 2. Normalize unprocessed raw posts ──────────────────────────────
        with tracer.start_as_current_span("normalize_posts"):
            raw_rows = db.fetch_unprocessed_raw_posts(limit=1000)
            norm_rows = []
            for r in raw_rows:
                clean = normalize_text(r["raw_text"])
                if len(clean) < 5:
                    continue
                norm_rows.append({
                    "raw_post_id": r["id"],
                    "platform":    r["platform"],
                    "post_id":     r["post_id"],
                    "clean_text":  clean,
                    "char_count":  len(clean),
                    "word_count":  len(clean.split()),
                    "posted_at":   r["posted_at"],
                })
            insert_normalized_posts(norm_rows)

        # ── 3 & 4. Classify unclassified posts ──────────────────────────────
        with tracer.start_as_current_span("classify_posts"):
            unclassified = db.fetch_unclassified_posts(limit=500)
            if unclassified:
                rel_clf  = _get_relevance()
                sent_clf = _get_sentiment()
                texts    = [r["clean_text"] for r in unclassified]

                t2 = time.time()
                # Relevance
                with tracer.start_as_current_span("relevance_filter"):
                    rel_results = rel_clf.classify_batch(texts)

                # Sentiment — only run on relevant posts
                relevant_indices = [
                    i for i, r in enumerate(rel_results) if r.is_relevant
                ]
                relevant_texts = [texts[i] for i in relevant_indices]

                sent_map: dict[int, object] = {}
                with tracer.start_as_current_span("sentiment_classify"):
                    if relevant_texts:
                        sent_results = sent_clf.classify_batch(relevant_texts)
                        for idx, sent in zip(relevant_indices, sent_results):
                            sent_map[idx] = sent
                            if sent.label == "positive":
                                METRICS.sentiment_positive_total.labels(
                                    platform=unclassified[idx]["platform"]
                                ).inc()
                                summary["positive"] += 1
                            elif sent.label == "negative":
                                METRICS.sentiment_negative_total.labels(
                                    platform=unclassified[idx]["platform"]
                                ).inc()
                                summary["negative"] += 1
                            elif sent.label == "neutral":
                                METRICS.sentiment_neutral_total.labels(
                                    platform=unclassified[idx]["platform"]
                                ).inc()
                                summary["neutral"] += 1

                # Persist
                clf_run_id = new_run_id()
                result_rows = []
                for i, (row, rel) in enumerate(zip(unclassified, rel_results)):
                    if rel.is_relevant:
                        summary["relevant"] += 1
                        METRICS.posts_relevant_total.labels(
                            platform=row["platform"]
                        ).inc()
                    else:
                        METRICS.posts_irrelevant_total.labels(
                            platform=row["platform"]
                        ).inc()

                    sent = sent_map.get(i)
                    influence = estimate_influence(dict(row))
                    METRICS.brand_relevance_confidence.observe(rel.score)

                    result_rows.append({
                        "normalized_post_id": row["id"],
                        "platform":           row["platform"],
                        "post_id":            row["post_id"],
                        "classifier_run_id":  clf_run_id,
                        "is_relevant":        rel.is_relevant,
                        "relevance_score":    rel.score,
                        "relevance_method":   rel.method,
                        "sentiment_label":    sent.label  if sent else None,
                        "sentiment_score":    sent.score  if sent else None,
                        "sentiment_raw_pos":  sent.raw_pos if sent else None,
                        "sentiment_raw_neu":  sent.raw_neu if sent else None,
                        "sentiment_raw_neg":  sent.raw_neg if sent else None,
                        "derived_labels":     rel.derived_labels,
                        "influence_weight":   influence,
                        "posted_at":          row["posted_at"],
                    })

                upsert_sentiment_results(result_rows)
                dur_cls = int((time.time() - t2) * 1000)
                METRICS.pipeline_duration.labels(stage="classify").observe(
                    dur_cls / 1000
                )
                logger.info(
                    "classification_complete",
                    extra={
                        "clf_run_id": clf_run_id,
                        "total": len(unclassified),
                        "relevant": summary["relevant"],
                        "duration_ms": dur_cls,
                    },
                )

        total_dur = int((time.time() - t0) * 1000)
        METRICS.pipeline_duration.labels(stage="total").observe(total_dur / 1000)
        logger.info("ingest_pipeline_complete", extra={"summary": summary, "duration_ms": total_dur})
        return summary


def _get_scraper(platform: str):
    if platform == "reddit":
        from scraper.reddit import RedditScraper
        return RedditScraper()
    if platform == "twitter":
        from scraper.twitter import TwitterScraper
        return TwitterScraper()
    raise ValueError(f"Unknown platform: {platform}")


if __name__ == "__main__":
    import sys
    logging.basicConfig(level="INFO")
    db.init_db()
    result = asyncio.run(run_ingest_pipeline())
    print(result)
    sys.exit(0 if not result["errors"] else 1)
