#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# Social Sentiment Pipeline — cron entrypoint
# Runs: ingest → aggregate → alert evaluation
# Designed to be called by cron or the Docker scheduler service.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."

export PYTHONPATH="$(pwd):$PYTHONPATH"

LOG_PREFIX="[social-sentiment][$(date -u +%Y-%m-%dT%H:%M:%SZ)]"

echo "$LOG_PREFIX Starting pipeline run"

python -m pipeline.ingest
echo "$LOG_PREFIX Ingest complete"

python -m pipeline.aggregate
echo "$LOG_PREFIX Aggregation complete"

python -m alerts.evaluator
echo "$LOG_PREFIX Alert evaluation complete"

echo "$LOG_PREFIX Pipeline run finished"
