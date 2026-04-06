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


if __name__ == "__main__":
    init_db()

    # Start metrics server
    from metrics.exporter import start_metrics_server

    start_metrics_server()

    logger.info("scheduler_starting", extra={"interval_minutes": INTERVAL})

    schedule.every(INTERVAL).minutes.do(run_pipeline)
    schedule.every().day.at("03:00").do(run_daily_purge)

    # Run once immediately on startup
    run_pipeline()

    while True:
        schedule.run_pending()
        time.sleep(30)
