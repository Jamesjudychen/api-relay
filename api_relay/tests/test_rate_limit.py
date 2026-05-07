"""Tests for the rate limiting module."""

from __future__ import annotations

import pytest

from api_relay.rate_limit import SlidingWindowCounter


@pytest.mark.asyncio
async def test_rate_limit_allows_requests_within_limit():
    """Test that requests within the limit are allowed."""
    counter = SlidingWindowCounter()

    # Should allow all requests up to the limit
    for _ in range(5):
        allowed = await counter.check_and_increment(
            key="test:key1", limit=5, window=60
        )
        assert allowed is True


@pytest.mark.asyncio
async def test_rate_limit_blocks_excess_requests():
    """Test that requests exceeding the limit are blocked."""
    counter = SlidingWindowCounter()
    key = "test:key2"

    # Use up the limit
    for _ in range(5):
        await counter.check_and_increment(key=key, limit=5, window=60)

    # Next request should be blocked
    allowed = await counter.check_and_increment(key=key, limit=5, window=60)
    assert allowed is False


@pytest.mark.asyncio
async def test_rate_limit_independent_keys():
    """Test that different keys have independent counters."""
    counter = SlidingWindowCounter()

    # Fill up key1
    for _ in range(5):
        await counter.check_and_increment(key="test:independent_a", limit=5, window=60)

    # key1 should be blocked
    assert await counter.check_and_increment(key="test:independent_a", limit=5, window=60) is False

    # key2 should still be allowed
    assert await counter.check_and_increment(key="test:independent_b", limit=5, window=60) is True


@pytest.mark.asyncio
async def test_rate_limit_different_windows():
    """Test rate limiting with different window sizes."""
    counter = SlidingWindowCounter()

    # 10 requests per second (tight window)
    key = "test:tight_window"

    for _ in range(10):
        assert await counter.check_and_increment(key=key, limit=10, window=1) is True

    assert await counter.check_and_increment(key=key, limit=10, window=1) is False
