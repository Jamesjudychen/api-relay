"""Rate limiting — sliding window algorithm."""

from __future__ import annotations

import math
import time
from typing import Optional

from api_relay.db import get_db


class SlidingWindowCounter:
    """Sliding window rate limiter backed by SQLite.

    Uses a weighted estimate between the current and previous time windows
    to avoid hard reset boundaries while remaining efficient.
    """

    def __init__(self) -> None:
        self._cleanup_interval: float = 300.0  # seconds between cleanups
        self._last_cleanup: float = 0.0

    async def check_and_increment(
        self,
        key: str,
        limit: int,
        window: int,
    ) -> bool:
        """Check and record a request.

        Args:
            key: Partition key (e.g. key_hash or client IP).
            limit: Maximum requests allowed in the window.
            window: Window duration in seconds.

        Returns:
            True if the request is allowed (within limit).
        """
        now = time.time()
        current_window = math.floor(now / window) * window
        prev_window = current_window - window
        current_key = f"{key}:{current_window}"
        prev_key = f"{key}:{prev_window}"

        db = await get_db()

        # Get counters for current and previous windows
        cur_count = await self._get_counter(db, current_key)
        prev_count = await self._get_counter(db, prev_key)

        # Weighted estimate: how far into the current window are we?
        weight = (now - current_window) / window
        estimate = (prev_count * (1.0 - weight)) + cur_count

        if estimate >= limit:
            return False

        # Record this request
        expires_at = now + window * 2  # keep for 2x window duration
        await self._increment_counter(db, current_key, expires_at)
        await self._periodic_cleanup(db, now)

        return True

    async def _get_counter(self, db, partition_key: str) -> int:
        cursor = await db.execute(
            "SELECT counter FROM rate_limit_counters WHERE partition_key = ?",
            (partition_key,),
        )
        row = await cursor.fetchone()
        return row[0] if row else 0

    async def _increment_counter(
        self, db, partition_key: str, expires_at: float
    ) -> None:
        await db.execute(
            """INSERT INTO rate_limit_counters (partition_key, counter, expires_at)
               VALUES (?, 1, ?)
               ON CONFLICT(partition_key) DO UPDATE SET counter = counter + 1""",
            (partition_key, expires_at),
        )
        await db.commit()

    async def _periodic_cleanup(self, db, now: float) -> None:
        if now - self._last_cleanup > self._cleanup_interval:
            await db.execute(
                "DELETE FROM rate_limit_counters WHERE expires_at < ?",
                (now,),
            )
            await db.commit()
            self._last_cleanup = now
