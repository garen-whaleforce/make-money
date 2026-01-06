"""SQLite storage"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


class SQLiteStore:
    """SQLite-based storage for caching and history"""

    def __init__(self, db_path: str = "data/cache.db"):
        """Initialize SQLite store.

        Args:
            db_path: Path to SQLite database
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    created_at REAL,
                    expires_at REAL
                );

                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    url TEXT,
                    published_at TEXT,
                    publisher TEXT,
                    tickers TEXT,
                    themes TEXT,
                    score REAL,
                    created_at REAL
                );

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    edition TEXT,
                    status TEXT,
                    primary_event_id TEXT,
                    research_pack_path TEXT,
                    post_path TEXT,
                    ghost_url TEXT,
                    created_at REAL,
                    completed_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at);
                CREATE INDEX IF NOT EXISTS idx_events_published ON events(published_at);
                CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at);
            """)

    # Cache methods
    def cache_get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()

            if not row:
                return None

            if time.time() > row[1]:
                conn.execute("DELETE FROM cache WHERE key = ?", (key,))
                return None

            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return row[0]

    def cache_set(self, key: str, value: Any, ttl: int = 3600) -> None:
        """Set value in cache"""
        with sqlite3.connect(self.db_path) as conn:
            value_str = json.dumps(value) if not isinstance(value, str) else value
            conn.execute(
                """
                INSERT OR REPLACE INTO cache (key, value, created_at, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, value_str, time.time(), time.time() + ttl)
            )

    def cache_delete(self, key: str) -> None:
        """Delete value from cache"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM cache WHERE key = ?", (key,))

    def cache_cleanup(self) -> int:
        """Remove expired cache entries. Returns count of deleted entries."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM cache WHERE expires_at < ?",
                (time.time(),)
            )
            return cursor.rowcount

    # Event methods
    def save_event(self, event: dict) -> None:
        """Save event to database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO events
                (id, title, url, published_at, publisher, tickers, themes, score, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("id"),
                    event.get("title"),
                    event.get("url"),
                    event.get("published_at"),
                    event.get("publisher"),
                    json.dumps(event.get("related_tickers", [])),
                    json.dumps(event.get("related_themes", [])),
                    event.get("score", 0),
                    time.time(),
                )
            )

    def get_recent_events(self, limit: int = 100) -> list[dict]:
        """Get recent events"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM events
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    def event_exists(self, event_id: str) -> bool:
        """Check if event already exists"""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT 1 FROM events WHERE id = ?",
                (event_id,)
            )
            return cursor.fetchone() is not None

    # Run methods
    def save_run(self, run: dict) -> None:
        """Save run record"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO runs
                (run_id, edition, status, primary_event_id, research_pack_path,
                 post_path, ghost_url, created_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.get("run_id"),
                    run.get("edition"),
                    run.get("status"),
                    run.get("primary_event_id"),
                    run.get("research_pack_path"),
                    run.get("post_path"),
                    run.get("ghost_url"),
                    run.get("created_at", time.time()),
                    run.get("completed_at"),
                )
            )

    def get_recent_runs(self, limit: int = 20) -> list[dict]:
        """Get recent runs"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """
                SELECT * FROM runs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]
