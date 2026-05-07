"""Tests for configuration loading and hot-reload."""

from __future__ import annotations

import os
import tempfile

import yaml

from api_relay.config import GatewayConfig, load_config


def test_default_config():
    """Test that default config values are reasonable."""
    cfg = GatewayConfig()
    assert cfg.host == "127.0.0.1"
    assert cfg.port == 9000
    assert cfg.default_rate_limit.requests == 60
    assert cfg.default_rate_limit.window_seconds == 60
    assert cfg.ip_rate_limit.requests == 120


def test_load_config_from_yaml():
    """Test loading configuration from a YAML file."""
    data = {
        "host": "0.0.0.0",
        "port": 8080,
        "default_rate_limit": {"requests": 100, "window_seconds": 30},
        "providers": {
            "test": {
                "base_url": "https://api.example.com/v1",
                "default_headers": {"Authorization": "Bearer test-key"},
            }
        },
        "routes": [
            {
                "name": "test-route",
                "match_type": "path_prefix",
                "match_value": "/test",
                "target_url": "https://api.example.com/v1",
            }
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        fpath = f.name

    try:
        cfg = load_config(fpath)
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8080
        assert cfg.default_rate_limit.requests == 100
        assert len(cfg.providers) == 1
        assert cfg.providers["test"].base_url == "https://api.example.com/v1"
        assert len(cfg.routes) == 1
        assert cfg.routes[0].name == "test-route"
    finally:
        os.unlink(fpath)


def test_env_var_resolution():
    """Test that ${VAR} syntax is resolved from environment."""
    os.environ["TEST_API_KEY"] = "sk-test123456"
    os.environ["TEST_API_URL"] = "https://custom.example.com"

    data = {
        "providers": {
            "custom": {
                "base_url": "${TEST_API_URL}/v1",
                "default_headers": {"Authorization": "Bearer ${TEST_API_KEY}"},
            }
        },
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        yaml.dump(data, f)
        fpath = f.name

    try:
        cfg = load_config(fpath)
        assert cfg.providers["custom"].base_url == "https://custom.example.com/v1"
        assert cfg.providers["custom"].default_headers["Authorization"] == "Bearer sk-test123456"
    finally:
        os.unlink(fpath)
        del os.environ["TEST_API_KEY"]
        del os.environ["TEST_API_URL"]


def test_empty_config_file():
    """Test loading an empty config file returns defaults."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write("")
        fpath = f.name

    try:
        cfg = load_config(fpath)
        assert cfg.host == "127.0.0.1"
        assert cfg.port == 9000
    finally:
        os.unlink(fpath)


def test_route_rule_defaults():
    """Test that route rules get sensible defaults."""
    rule = {
        "name": "my-route",
        "match_type": "path_prefix",
        "match_value": "/api",
        "target_url": "https://upstream.example.com",
    }

    from api_relay.config import RouteRule

    r = RouteRule(**rule)
    assert r.strip_prefix is True
    assert r.timeout_seconds == 30
    assert r.target_headers == {}
