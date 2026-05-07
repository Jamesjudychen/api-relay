"""API Key authentication — generation, hashing, and verification."""

from __future__ import annotations

import hashlib
import secrets
from typing import Any, Dict, Optional, Tuple

from api_relay.db import create_api_key, get_api_key_by_hash


def generate_key() -> Tuple[str, str]:
    """Generate a new API key.

    Returns:
        Tuple of (raw_key, key_hash). Only the hash should be stored.
    """
    raw = f"ag_{secrets.token_hex(24)}"
    h = _hash_key(raw)
    return raw, h


def _hash_key(raw: str) -> str:
    """Return the SHA-256 hex digest of a raw key."""
    return hashlib.sha256(raw.encode()).hexdigest()


async def authenticate(token: str) -> Optional[Dict[str, Any]]:
    """Authenticate a Bearer token against the database.

    Args:
        token: The raw API key from the Authorization header.

    Returns:
        Key record dict if valid and active, or None.
    """
    key_hash = _hash_key(token)
    record = await get_api_key_by_hash(key_hash)
    if record is None:
        return None
    if not record["is_active"]:
        return None

    # Check expiry
    expires_at = record.get("expires_at")
    if expires_at:
        from datetime import datetime, timezone

        try:
            expiry = datetime.fromisoformat(expires_at)
            if expiry.tzinfo is None:
                from datetime import timezone as tz

                expiry = expiry.replace(tzinfo=tz.utc)
            if expiry < datetime.now(timezone.utc):
                return None
        except ValueError:
            return None

    return record


async def create_key_record(
    name: str,
    role: str = "user",
    rate_limit_requests: Optional[int] = None,
    rate_limit_window: Optional[int] = None,
    metadata: Optional[Dict[str, Any]] = None,
    expires_at: Optional[str] = None,
) -> Tuple[str, int]:
    """Generate a new API key and store its hash in the database.

    Returns:
        Tuple of (raw_key, db_row_id).
    """
    raw, key_hash = generate_key()
    key_prefix = raw[:12]  # e.g. "ag_abc123def456"
    row_id = await create_api_key(
        key_hash=key_hash,
        key_prefix=key_prefix,
        name=name,
        role=role,
        rate_limit_requests=rate_limit_requests,
        rate_limit_window=rate_limit_window,
        metadata=metadata,
        expires_at=expires_at,
    )
    return raw, row_id
