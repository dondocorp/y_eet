#!/usr/bin/env python3
"""Initialize the SQLite database. Safe to run multiple times (idempotent)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from storage.db import init_db, DB_PATH
from observability.logger import configure_logging

configure_logging()

print(f"Initializing DB at: {DB_PATH}")
init_db()
print("DB initialized successfully.")
