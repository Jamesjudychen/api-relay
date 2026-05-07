"""Tests for the routing engine."""

from __future__ import annotations

from api_relay.config import GatewayConfig, RouteRule
from api_relay.routing import RouterEngine


def test_path_prefix_matching():
    """Test basic path prefix route matching."""
    config = GatewayConfig(
        routes=[
            RouteRule(
                name="openai",
                match_type="path_prefix",
                match_value="/openai",
                target_url="https://api.openai.com/v1",
                strip_prefix=True,
            ),
            RouteRule(
                name="anthropic",
                match_type="path_prefix",
                match_value="/anthropic",
                target_url="https://api.anthropic.com/v1",
                strip_prefix=True,
            ),
        ]
    )

    engine = RouterEngine(config)

    # Test OpenAI match
    match = engine.match("POST", "/openai/chat/completions", {})
    assert match is not None
    assert match.upstream_url == "https://api.openai.com/v1/chat/completions"

    # Test Anthropic match
    match = engine.match("POST", "/anthropic/messages", {})
    assert match is not None
    assert match.upstream_url == "https://api.anthropic.com/v1/messages"

    # Test no match
    match = engine.match("GET", "/unknown/path", {})
    assert match is None


def test_path_prefix_no_strip():
    """Test path prefix matching without stripping the prefix."""
    config = GatewayConfig(
        routes=[
            RouteRule(
                name="passthrough",
                match_type="path_prefix",
                match_value="/proxy",
                target_url="https://api.example.com",
                strip_prefix=False,
            ),
        ]
    )

    engine = RouterEngine(config)
    match = engine.match("GET", "/proxy/some/path", {})
    assert match is not None
    assert match.upstream_url == "https://api.example.com/proxy/some/path"


def test_header_matching():
    """Test header-based route matching."""
    config = GatewayConfig(
        routes=[
            RouteRule(
                name="header-route",
                match_type="header",
                match_value="X-Provider: custom",
                target_url="https://custom.example.com/v1",
                strip_prefix=True,
            ),
        ]
    )

    engine = RouterEngine(config)

    # Match with correct header
    match = engine.match("GET", "/chat", {"x-provider": "custom"})
    assert match is not None
    assert match.upstream_url == "https://custom.example.com/v1/chat"

    # No match with wrong header
    match = engine.match("GET", "/chat", {"x-provider": "other"})
    assert match is None

    # No match with missing header
    match = engine.match("GET", "/chat", {})
    assert match is None


def test_body_jsonpath_matching():
    """Test body-based route matching (JSONPath-style)."""
    config = GatewayConfig(
        routes=[
            RouteRule(
                name="model-route",
                match_type="body_jsonpath",
                match_value="$.model=claude-*",
                target_url="https://api.anthropic.com/v1",
                strip_prefix=True,
            ),
        ]
    )

    engine = RouterEngine(config)

    # Match: model field starts with "claude-"
    match = engine.match("POST", "/messages", {}, {"model": "claude-opus-4-20250514"})
    assert match is not None
    assert "anthropic.com" in match.upstream_url

    # No match: different model
    match = engine.match("POST", "/messages", {}, {"model": "gpt-4"})
    assert match is None

    # No match: no body
    match = engine.match("POST", "/messages", {}, None)
    assert match is None


def test_first_match_wins():
    """Test that the first matching route is selected."""
    config = GatewayConfig(
        routes=[
            RouteRule(
                name="specific",
                match_type="path_prefix",
                match_value="/api/v2",
                target_url="https://v2.example.com",
                strip_prefix=True,
            ),
            RouteRule(
                name="general",
                match_type="path_prefix",
                match_value="/api",
                target_url="https://v1.example.com",
                strip_prefix=True,
            ),
        ]
    )

    engine = RouterEngine(config)

    match = engine.match("GET", "/api/v2/users", {})
    assert match is not None
    assert "v2.example.com" in match.upstream_url


def test_extra_headers_in_match():
    """Test that extra headers from route rules are included."""
    config = GatewayConfig(
        routes=[
            RouteRule(
                name="with-headers",
                match_type="path_prefix",
                match_value="/secure",
                target_url="https://secure.example.com",
                target_headers={"X-Custom": "value123"},
                strip_prefix=True,
            ),
        ]
    )

    engine = RouterEngine(config)
    match = engine.match("GET", "/secure/data", {})
    assert match is not None
    assert match.extra_headers == {"X-Custom": "value123"}
