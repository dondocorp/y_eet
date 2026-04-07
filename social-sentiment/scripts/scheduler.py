"""
In-process scheduler for Docker environments where cron isn't available.
Runs every N minutes via schedule library.
Set SCHEDULER_INTERVAL_MINUTES env var (default: 30).
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import schedule

from config.settings import LOG_LEVEL
from observability.logger import configure_logging
from storage.db import init_db, purge_old_data

configure_logging(LOG_LEVEL)
logger = logging.getLogger(__name__)

INTERVAL = int(os.getenv("SCHEDULER_INTERVAL_MINUTES", "30"))


def run_pipeline() -> None:
    try:
        from alerts.evaluator import run_alert_evaluation
        from pipeline.aggregate import run_aggregation
        from pipeline.ingest import run_ingest_pipeline

        logger.info("scheduler_pipeline_start")
        result = asyncio.run(run_ingest_pipeline())
        run_aggregation()
        run_alert_evaluation()
        logger.info("scheduler_pipeline_done", extra={"summary": result})
    except Exception as exc:
        logger.error("scheduler_pipeline_error", extra={"error": str(exc)})


def run_daily_purge() -> None:
    try:
        purge_old_data()
        logger.info("daily_purge_complete")
    except Exception as exc:
        logger.error("daily_purge_error", extra={"error": str(exc)})


def run_fetch_check() -> None:
    """
    Quick startup sanity check: hit the Reddit JSON endpoint for each configured
    brand query and log raw hit counts. No DB writes — purely diagnostic.
    """
    import json
    import urllib.request
    from urllib.parse import quote_plus
    from config.settings import BRAND_QUERIES

    REDDIT_URL = "https://www.reddit.com/search.json?q={q}&sort=new&t=week&limit=10"
    HEADERS = {"User-Agent": "social-sentiment-diag/1.0"}

    logger.info("fetch_check_start queries=%s", BRAND_QUERIES)
    total = 0
    for query in BRAND_QUERIES:
        url = REDDIT_URL.format(q=quote_plus(query))
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                count = len(data.get("data", {}).get("children", []))
                total += count
                logger.info(
                    "fetch_check_result query=%r raw_posts=%d", query, count
                )
        except Exception as exc:
            logger.warning("fetch_check_failed query=%r error=%s", query, exc)

    if total == 0:
        logger.warning(
            "fetch_check_zero_results — Reddit returned no posts for any brand query. "
            "Brand may have low Reddit activity or requests are being rate-limited."
        )
    else:
        logger.info("fetch_check_done total_raw_posts=%d", total)


if __name__ == "__main__":
    init_db()

    # Start metrics server
    from metrics.exporter import start_metrics_server

    start_metrics_server()

    logger.info("scheduler_starting", extra={"interval_minutes": INTERVAL})

    # Verify Reddit reachability before first pipeline run
    run_fetch_check()

    schedule.every(INTERVAL).minutes.do(run_pipeline)
    schedule.every().day.at("03:00").do(run_daily_purge)

    # Run once immediately on startup
    run_pipeline()

    while True:
        schedule.run_pending()
        time.sleep(30)
