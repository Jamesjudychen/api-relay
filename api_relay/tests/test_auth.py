"""Tests for API key authentication."""

from __future__ import annotations

import pytest

from api_relay.auth import authenticate, create_key_record, generate_key


@pytest.mark.asyncio
async def test_generate_key():
    """Test that generated keys have the correct format."""
    raw, key_hash = generate_key()

    assert raw.startswith("ag_")
    assert len(raw) > 20
    assert len(key_hash) == 64  # SHA-256 hex digest


@pytest.mark.asyncio
async def test_create_and_authenticate():
    """Test creating a key and authenticating with it."""
    raw, row_id = await create_key_record(
        name="test-key",
        role="user",
    )

    assert row_id > 0
    assert raw.startswith("ag_")

    # Authenticate with the raw key
    record = await authenticate(raw)
    assert record is not None
    assert record["name"] == "test-key"
    assert record["role"] == "user"
    assert record["is_active"] == 1


@pytest.mark.asyncio
async def test_authenticate_invalid_key():
    """Test that invalid keys return None."""
    record = await authenticate("ag_invalid_key_that_does_not_exist")
    assert record is None


@pytest.mark.asyncio
async def test_authenticate_expired_key():
    """Test that expired keys return None."""
    from datetime import datetime, timedelta, timezone

    expires = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

    raw, _ = await create_key_record(
        name="expired-key",
        role="user",
        expires_at=expires,
    )

    record = await authenticate(raw)
    assert record is None


@pytest.mark.asyncio
async def test_authenticate_deactivated_key():
    """Test that deactivated keys return None."""
    raw, row_id = await create_key_record(name="deact-key", role="user")

    # Deactivate the key
    from api_relay.db import update_api_key

    await update_api_key(row_id, is_active=0)

    record = await authenticate(raw)
    assert record is None


@pytest.mark.asyncio
async def test_admin_and_user_roles():
    """Test that admin and user keys are properly differentiated."""
    admin_raw, _ = await create_key_record(name="admin-key", role="admin")
    user_raw, _ = await create_key_record(name="user-key", role="user")

    admin_record = await authenticate(admin_raw)
    user_record = await authenticate(user_raw)

    assert admin_record["role"] == "admin"
    assert user_record["role"] == "user"
