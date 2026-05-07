"""Async SQLite database layer with WAL mode and schema management."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

import aiosqlite

DB: Optional[aiosqlite.Connection] = None

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version   INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_keys (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    key_hash            TEXT    NOT NULL UNIQUE,
    key_prefix          TEXT    NOT NULL,
    name                TEXT    NOT NULL,
    role                TEXT    NOT NULL DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    is_active           INTEGER NOT NULL DEFAULT 1,
    rate_limit_requests INTEGER,
    rate_limit_window   INTEGER,
    metadata            TEXT    DEFAULT '{}',
    expires_at          TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS rate_limit_counters (
    partition_key TEXT    NOT NULL,
    counter       INTEGER NOT NULL DEFAULT 0,
    expires_at    REAL    NOT NULL,
    PRIMARY KEY (partition_key)
);

CREATE TABLE IF NOT EXISTS request_logs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp          TEXT    NOT NULL DEFAULT (datetime('now')),
    method             TEXT    NOT NULL,
    path               TEXT    NOT NULL,
    query_string       TEXT,
    status_code        INTEGER,
    latency_ms         INTEGER,
    api_key_id         INTEGER REFERENCES api_keys(id) ON DELETE SET NULL,
    api_key_name       TEXT,
    upstream_url       TEXT,
    provider_name      TEXT,
    request_headers    TEXT,
    response_headers   TEXT,
    request_body_size  INTEGER,
    response_body_size INTEGER,
    client_ip          TEXT,
    error              TEXT
);

CREATE INDEX IF NOT EXISTS idx_logs_timestamp ON request_logs(timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_api_key  ON request_logs(api_key_id);
CREATE INDEX IF NOT EXISTS idx_logs_status   ON request_logs(status_code);
CREATE INDEX IF NOT EXISTS idx_logs_client   ON request_logs(client_ip);

CREATE INDEX IF NOT EXISTS idx_rate_limit_expires ON rate_limit_counters(expires_at);
"""


async def init_db(db_path: str) -> aiosqlite.Connection:
    """Initialize the database: open connection, apply schema."""
    global DB

    db_path = os.path.expanduser(db_path)
    parent = Path(db_path).parent
    parent.mkdir(parents=True, exist_ok=True)

    conn = await aiosqlite.connect(db_path)
    conn.row_factory = aiosqlite.Row

    await conn.executescript(SCHEMA_SQL)
    await conn.commit()

    DB = conn
    return conn


async def close_db() -> None:
    """Close the database connection."""
    global DB
    if DB is not None:
        await DB.close()
        DB = None


async def get_db() -> aiosqlite.Connection:
    """Get the current database connection."""
    assert DB is not None, "Database not initialized. Call init_db() first."
    return DB


# ─── API Key CRUD ────────────────────────────────────────────────────────────


async def create_api_key(
    key_hash: str,
    key_prefix: str,
    name: str,
    role: str = "user",
    rate_limit_requests: Optional[int] = None,
    rate_limit_window: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    expires_at: Optional[str] = None,
) -> int:
    """Insert a new API key record. Returns the row id."""
    db = await get_db()
    cursor = await db.execute(
        """INSERT INTO api_keys
           (key_hash, key_prefix, name, role, rate_limit_requests, rate_limit_window, metadata, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            key_hash,
            key_prefix,
            name,
            role,
            rate_limit_requests,
            rate_limit_window,
            json.dumps(metadata or {}),
            expires_at,
        ),
    )
    await db.commit()
    return cursor.lastrowid


async def get_api_key_by_hash(key_hash: str) -> Optional[Dict[str, Any]]:
    """Look up an API key by its hash."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def get_api_key_by_id(key_id: int) -> Optional[Dict[str, Any]]:
    """Look up an API key by its ID."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT * FROM api_keys WHERE id = ?", (key_id,)
    )
    row = await cursor.fetchone()
    if row is None:
        return None
    return dict(row)


async def list_api_keys(
    page: int = 1,
    page_size: int = 50,
    include_inactive: bool = False,
) -> Tuple[List[Dict[str, Any]], int]:
    """List API keys with pagination. Returns (keys, total_count)."""
    db = await get_db()

    where = "" if include_inactive else "WHERE is_active = 1"
    offset = (page - 1) * page_size

    cursor = await db.execute(
        f"SELECT COUNT(*) FROM api_keys {where}"
    )
    total = (await cursor.fetchone())[0]

    cursor = await db.execute(
        f"SELECT * FROM api_keys {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
        (page_size, offset),
    )
    rows = await cursor.fetchall()
    keys = [dict(r) for r in rows]

    return keys, total


async def update_api_key(
    key_id: int,
    **kwargs: Any,
) -> bool:
    """Update fields of an API key. Returns True if a row was updated."""
    allowed = {"name", "role", "is_active", "rate_limit_requests",
               "rate_limit_window", "metadata", "expires_at"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False

    if "metadata" in updates and isinstance(updates["metadata"], dict):
        updates["metadata"] = json.dumps(updates["metadata"])

    updates["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [key_id]

    db = await get_db()
    cursor = await db.execute(
        f"UPDATE api_keys SET {set_clause} WHERE id = ?", values
    )
    await db.commit()
    return cursor.rowcount > 0


async def delete_api_key(key_id: int) -> bool:
    """Soft-delete an API key by setting is_active = 0."""
    return await update_api_key(key_id, is_active=0)


# ─── Log Batching ────────────────────────────────────────────────────────────


_log_batch: List[Dict[str, Any]] = []


async def flush_logs() -> int:
    """Flush buffered log entries to DB. Returns number of rows written."""
    global _log_batch
    if not _log_batch:
        return 0

    db = await get_db()
    rows = _log_batch
    _log_batch = []

    await db.executemany(
        """INSERT INTO request_logs
           (timestamp, method, path, query_string, status_code, latency_ms,
            api_key_id, api_key_name, upstream_url, provider_name,
            request_headers, response_headers, request_body_size,
            response_body_size, client_ip, error)
           VALUES
           (:timestamp, :method, :path, :query_string, :status_code, :latency_ms,
            :api_key_id, :api_key_name, :upstream_url, :provider_name,
            :request_headers, :response_headers, :request_body_size,
            :response_body_size, :client_ip, :error)""",
        rows,
    )
    await db.commit()
    return len(rows)


def queue_log(entry: Dict[str, Any]) -> None:
    """Queue a log entry for batch insert."""
    global _log_batch
    _log_batch.append(entry)


async def clean_old_logs(retention_days: int = 30) -> int:
    """Remove logs older than retention_days. Returns number of rows deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM request_logs WHERE timestamp < datetime('now', ?)",
        (f"-{retention_days} days",),
    )
    await db.commit()
    return cursor.rowcount


async def clean_expired_rate_limiters() -> int:
    """Remove expired rate limit counter rows. Returns number of rows deleted."""
    db = await get_db()
    cursor = await db.execute(
        "DELETE FROM rate_limit_counters WHERE expires_at < ?",
        (time.time(),),
    )
    await db.commit()
    return cursor.rowcount


# ─── Stats ────────────────────────────────────────────────────────────────────


async def get_request_stats(
    since: Optional[str] = None,
) -> Dict[str, Any]:
    """Get aggregated request statistics."""
    db = await get_db()
    where = ""
    params: list = []
    if since:
        where = "WHERE timestamp >= ?"
        params.append(since)

    cursor = await db.execute(
        f"""SELECT
               COUNT(*) as total_requests,
               COALESCE(AVG(latency_ms), 0) as avg_latency_ms,
               COALESCE(MAX(latency_ms), 0) as max_latency_ms,
               COALESCE(SUM(CASE WHEN status_code >= 200 AND status_code < 300 THEN 1 ELSE 0 END), 0) as success_count,
               COALESCE(SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END), 0) as error_count
           FROM request_logs {where}""",
        params,
    )
    row = await cursor.fetchone()
    if row is None:
        return {}
    return dict(row)


async def count_active_keys() -> int:
    """Count active non-expired API keys."""
    db = await get_db()
    cursor = await db.execute(
        """SELECT COUNT(*) FROM api_keys
           WHERE is_active = 1
           AND (expires_at IS NULL OR expires_at > datetime('now'))"""
    )
    return (await cursor.fetchone())[0]
