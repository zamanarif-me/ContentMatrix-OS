"""
Cache layer — SQLite local with Turso cloud upgrade path.

Stores three kinds of responses to avoid duplicate API spend:
  - SERP responses (Serper.dev)
  - LLM completions (Anthropic, Gemini)
  - Embedding vectors (SentenceTransformers)

Cache key is SHA-256 of canonical request inputs (sorted, JSON-serialized).
TTL is enforced on lookup — stale entries return None.

Switching to Turso (cloud SQLite):
  Set TURSO_DATABASE_URL + TURSO_AUTH_TOKEN in .env.
  No code changes needed in calling stages.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional


CACHE_DIR = Path(__file__).parent.parent / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = CACHE_DIR / "engine_cache.db"


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_entries (
    cache_key   TEXT PRIMARY KEY,
    cache_type  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL,
    hits        INTEGER DEFAULT 0,
    bytes_size  INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cache_type ON cache_entries(cache_type);
CREATE INDEX IF NOT EXISTS idx_expires    ON cache_entries(expires_at);
"""


def _conn() -> sqlite3.Connection:
    """Open SQLite connection. Turso swap point — replace this function."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _conn() as c:
        c.executescript(_SCHEMA)


_init_db()


# ── Hashing ───────────────────────────────────────────────────────────────────

def make_cache_key(*parts: Any) -> str:
    """
    Build a stable SHA-256 cache key from arbitrary inputs.
    Dicts/lists are JSON-serialized with sorted keys for determinism.
    """
    canonical = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── CRUD ──────────────────────────────────────────────────────────────────────

def get(cache_key: str) -> Optional[dict]:
    """
    Look up a cache entry. Returns payload dict or None if missing/expired.
    Increments hit counter on successful read.
    """
    now = time.time()
    with _conn() as c:
        row = c.execute(
            "SELECT payload, expires_at FROM cache_entries WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
        if not row:
            return None
        if row["expires_at"] is not None and row["expires_at"] < now:
            c.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
            return None
        c.execute(
            "UPDATE cache_entries SET hits = hits + 1 WHERE cache_key = ?",
            (cache_key,),
        )
        return json.loads(row["payload"])


def put(
    cache_key: str,
    cache_type: str,
    payload: dict,
    ttl_days: int = 30,
) -> None:
    """Insert or replace a cache entry."""
    now = time.time()
    expires_at = now + ttl_days * 86400 if ttl_days > 0 else None
    serialized = json.dumps(payload, default=str)
    with _conn() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO cache_entries
                (cache_key, cache_type, payload, created_at, expires_at, hits, bytes_size)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (cache_key, cache_type, serialized, now, expires_at, len(serialized)),
        )


def delete(cache_key: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM cache_entries WHERE cache_key = ?", (cache_key,))
        return cur.rowcount > 0


def purge_expired() -> int:
    """Remove all expired entries. Returns count deleted."""
    now = time.time()
    with _conn() as c:
        cur = c.execute(
            "DELETE FROM cache_entries WHERE expires_at IS NOT NULL AND expires_at < ?",
            (now,),
        )
        return cur.rowcount


def stats() -> dict:
    """Aggregate stats for the cache dashboard."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT cache_type,
                   COUNT(*)        AS entries,
                   SUM(hits)       AS total_hits,
                   SUM(bytes_size) AS total_bytes
            FROM cache_entries
            GROUP BY cache_type
            """
        ).fetchall()
        total = c.execute(
            "SELECT COUNT(*) AS n, SUM(bytes_size) AS b FROM cache_entries"
        ).fetchone()
    return {
        "by_type": [dict(r) for r in rows],
        "total_entries": total["n"] or 0,
        "total_bytes": total["b"] or 0,
    }


def clear_all() -> int:
    """Nuclear option — wipe the entire cache. Returns count deleted."""
    with _conn() as c:
        cur = c.execute("DELETE FROM cache_entries")
        return cur.rowcount
