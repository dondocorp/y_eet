#!/usr/bin/env python3
"""
Diagnostic script — tests the full brand intelligence pipeline end-to-end
without Playwright or the scheduler. Runs entirely via HTTP (requests lib).

Usage (inside the container or with deps installed):
  PYTHONPATH=/app python3 scripts/test_fetch.py
  PYTHONPATH=/app python3 scripts/test_fetch.py --query "yeet casino" --limit 20

What it checks:
  1. Reddit JSON endpoint reachability and raw hit count
  2. Relevance classifier pass-through rate
  3. What gets filtered and why
  4. DB write round-trip (optional, --write flag)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote_plus

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests

REDDIT_JSON = "https://www.reddit.com/search.json?q={q}&sort=new&t=week&limit={limit}"
HEADERS = {"User-Agent": "brand-intel-diag/1.0 (diagnostic script)"}


def fetch_reddit(query: str, limit: int = 25) -> list[dict]:
    url = REDDIT_JSON.format(q=quote_plus(query), limit=limit)
    print(f"\n[Reddit] GET {url}")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        print(f"  HTTP {r.status_code}  ({len(r.content)} bytes)")
        if r.status_code != 200:
            print(f"  ERROR: {r.text[:300]}")
            return []
        data = r.json()
        children = data.get("data", {}).get("children", [])
        print(f"  Raw posts returned: {len(children)}")
        return [c["data"] for c in children]
    except Exception as exc:
        print(f"  EXCEPTION: {exc}")
        return []


def check_relevance(posts: list[dict], query: str) -> None:
    try:
        from nlp.relevance import BrandRelevanceClassifier

        clf = BrandRelevanceClassifier()
    except ImportError as exc:
        print(f"\n[Relevance] Cannot import classifier: {exc}")
        print("  (Install deps or run inside the container)")
        return

    relevant = []
    filtered = []

    for post in posts:
        title = post.get("title", "")
        body = post.get("selftext", "")
        text = f"{title} {body}".strip()
        if not text:
            continue
        result = clf.classify(text)
        if result.is_relevant:
            relevant.append((text[:80], result.score, result.derived_labels))
        else:
            filtered.append((text[:80], result.score))

    print(f"\n[Relevance] query='{query}'")
    print(f"  Classified:  {len(relevant) + len(filtered)}")
    print(f"  Relevant:    {len(relevant)}")
    print(f"  Filtered:    {len(filtered)}")

    if relevant:
        print("\n  --- RELEVANT POSTS ---")
        for text, score, labels in relevant[:10]:
            print(f"    [{score:.2f}] {labels} | {text!r}")
    else:
        print("\n  No relevant posts found for this query.")

    if filtered:
        print("\n  --- FILTERED OUT (sample) ---")
        for text, score in filtered[:5]:
            print(f"    [{score:.2f}] {text!r}")


def test_db_write() -> None:
    try:
        from storage.db import get_connection, init_db, insert_scrape_run, finish_scrape_run

        init_db()
        run_id = insert_scrape_run(platform="reddit", query="[diag-test]")
        finish_scrape_run(run_id, status="success", posts_found=0)
        with get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM scrape_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        print(f"\n[DB] Write round-trip: OK  (run_id={run_id}, status={row['status']})")

        # Clean up
        with get_connection() as conn:
            conn.execute("DELETE FROM scrape_runs WHERE run_id=?", (run_id,))
            conn.commit()
    except Exception as exc:
        print(f"\n[DB] Write round-trip FAILED: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Brand intelligence diagnostic")
    parser.add_argument("--query", default=None, help="Override brand query (default: all from settings)")
    parser.add_argument("--limit", type=int, default=25, help="Max Reddit posts per query")
    parser.add_argument("--write", action="store_true", help="Test DB write round-trip")
    parser.add_argument("--no-relevance", action="store_true", help="Skip relevance classifier")
    args = parser.parse_args()

    # Load brand queries from settings
    try:
        from config.settings import BRAND_QUERIES
        queries = [args.query] if args.query else BRAND_QUERIES
    except ImportError:
        queries = [args.query or "yeet casino"]

    print("=" * 60)
    print("Brand Intelligence — Diagnostic Fetch")
    print("=" * 60)
    print(f"Queries : {queries}")
    print(f"Limit   : {args.limit} posts per query")

    total_raw = 0
    all_posts_by_query: dict[str, list[dict]] = {}

    for query in queries:
        posts = fetch_reddit(query, limit=args.limit)
        all_posts_by_query[query] = posts
        total_raw += len(posts)
        time.sleep(1)  # polite rate limit between queries

    print(f"\n[Summary] Total raw posts fetched: {total_raw}")

    if total_raw == 0:
        print("\n  DIAGNOSIS: Reddit returned 0 posts.")
        print("  Possible causes:")
        print("    1. The brand has very little Reddit activity")
        print("    2. The search query is too specific — try --query 'yeet' for broader results")
        print("    3. Reddit rate-limited the request (User-Agent or IP blocked)")
        print("    4. Network issue from inside the container (check DNS/proxy)")
        print("\n  Try:")
        print("    python3 scripts/test_fetch.py --query 'yeet' --limit 50")
        print("    python3 scripts/test_fetch.py --query 'online casino' --limit 20")
        return

    if not args.no_relevance:
        for query, posts in all_posts_by_query.items():
            if posts:
                check_relevance(posts, query)

    if args.write:
        test_db_write()

    print("\n" + "=" * 60)
    print("Diagnostic complete.")


if __name__ == "__main__":
    main()
