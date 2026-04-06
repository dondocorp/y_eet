"""Shared pytest fixtures for the social sentiment test suite."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Ensure imports work from repo root
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture
def tmp_db(tmp_path):
    """Fresh in-memory-equivalent SQLite DB for each test."""
    from storage.db import init_db
    db_path = tmp_path / "test_social.db"
    init_db(db_path)
    return db_path


@pytest.fixture
def sample_posts():
    return [
        {
            "post_id": "111",
            "platform": "reddit",
            "scrape_run_id": "run-test-001",
            "raw_text": "Yeet Casino just stole my withdrawal, total scam!",
            "author_handle": "angry_gambler",
            "posted_at": "2024-01-15T14:30:00Z",
            "likes": 10, "reposts": 2, "replies": 5, "upvotes": 45,
        },
        {
            "post_id": "222",
            "platform": "reddit",
            "scrape_run_id": "run-test-001",
            "raw_text": "Yeet Casino paid out fast! Best casino ever!",
            "author_handle": "happy_user",
            "posted_at": "2024-01-15T14:45:00Z",
            "likes": 100, "reposts": 5, "replies": 10, "upvotes": 200,
        },
        {
            "post_id": "333",
            "platform": "twitter",
            "scrape_run_id": "run-test-001",
            "raw_text": "lol yeet that ball haha",  # irrelevant
            "author_handle": "sport_fan",
            "posted_at": "2024-01-15T14:00:00Z",
        },
    ]
