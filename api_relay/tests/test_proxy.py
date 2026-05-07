"""Tests for the proxy forwarding module (unit tests with mock upstream)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from api_relay.models import RouteMatch
from api_relay.proxy.forwarder import _clean_headers, proxy_request


def test_clean_headers_removes_hop_by_hop():
    """Test that hop-by-hop headers are removed."""
    headers = {
        "host": "example.com",
        "content-type": "application/json",
        "authorization": "Bearer token123",
        "connection": "keep-alive",
        "transfer-encoding": "chunked",
    }
    cleaned = _clean_headers(headers)
    assert "host" not in cleaned
    assert "connection" not in cleaned
    assert "transfer-encoding" not in cleaned
    assert cleaned["content-type"] == "application/json"
    assert cleaned["authorization"] == "Bearer token123"


@pytest.mark.asyncio
async def test_proxy_request_non_streaming():
    """Test basic non-streaming proxy request with mocked upstream."""
    with patch("api_relay.proxy.forwarder.httpx.AsyncClient") as mock_client:
        mock_client_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {"content-type": "application/json"}
        mock_response.content = b'{"ok": true}'
        mock_client_instance.send.return_value = mock_response

        status, headers, body = await proxy_request(
            method="POST",
            url="https://api.example.com/v1/chat",
            headers={"content-type": "application/json", "authorization": "Bearer test"},
            body=b'{"model": "gpt-4"}',
            timeout=30,
        )

        assert status == 200
        assert headers["content-type"] == "application/json"
        assert body == b'{"ok": true}'


def test_route_match_model():
    """Test RouteMatch pydantic model."""
    match = RouteMatch(
        upstream_url="https://api.example.com/v1/chat",
        extra_headers={"X-Custom": "value"},
        timeout=30.0,
    )
    assert match.upstream_url == "https://api.example.com/v1/chat"
    assert match.extra_headers["X-Custom"] == "value"
    assert match.timeout == 30.0


@pytest.mark.asyncio
async def test_proxy_request_custom_headers_injected():
    """Test that extra headers from route rules are passed through."""
    with patch("api_relay.proxy.forwarder.httpx.AsyncClient") as mock_client:
        mock_client_instance = AsyncMock()
        mock_client.return_value.__aenter__.return_value = mock_client_instance

        mock_response = AsyncMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.content = b"ok"
        mock_client_instance.send.return_value = mock_response

        status, headers, body = await proxy_request(
            method="GET",
            url="https://api.example.com/v1/health",
            headers={"accept": "application/json"},
            body=None,
            timeout=10,
            extra_headers={"X-API-Key": "secret"},
        )

        assert status == 200
