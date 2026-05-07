"""Configuration models, YAML loading, and hot-reload watcher."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Callable, Coroutine, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class RateLimitRule(BaseModel):
    requests: int = 60
    window_seconds: int = 60


class RouteRule(BaseModel):
    name: str
    match_type: str  # "path_prefix" | "header" | "body_jsonpath"
    match_value: str
    target_url: str
    target_headers: Dict[str, str] = {}
    strip_prefix: bool = True
    timeout_seconds: int = 30


class ProviderConfig(BaseModel):
    base_url: str
    default_headers: Dict[str, str] = {}
    timeout_seconds: int = 30


class ApiKeySeedConfig(BaseModel):
    admin_keys: List[str] = []
    user_keys: List[str] = []


class CorsConfig(BaseModel):
    allow_origins: List[str] = ["*"]
    allow_methods: List[str] = ["*"]
    allow_headers: List[str] = ["*"]


class GatewayConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 9000
    log_level: str = "INFO"
    db_path: str = "~/.api_relay/data.db"

    default_rate_limit: RateLimitRule = RateLimitRule(requests=60, window_seconds=60)
    ip_rate_limit: RateLimitRule = RateLimitRule(requests=120, window_seconds=60)

    providers: Dict[str, ProviderConfig] = {}
    routes: List[RouteRule] = []
    api_keys: ApiKeySeedConfig = ApiKeySeedConfig()
    cors: Optional[CorsConfig] = None

    config_reload_seconds: int = 30
    log_retention_days: int = 30
    batch_log_flush_interval: float = 5.0
    batch_log_flush_count: int = 100


def _resolve_env_vars(value: str) -> str:
    """Resolve ${VAR_NAME} or $VAR_NAME environment variables."""
    return os.path.expandvars(value)


def _resolve_config(obj):
    """Recursively resolve env vars in all string values in a config object."""
    if isinstance(obj, str):
        return _resolve_env_vars(obj)
    if isinstance(obj, dict):
        return {k: _resolve_config(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_resolve_config(item) for item in obj]
    return obj


def load_config(path: str) -> GatewayConfig:
    """Load and parse a YAML configuration file."""
    path = os.path.expanduser(path)
    with open(path) as f:
        raw = yaml.safe_load(f)
    if raw is None:
        raw = {}
    resolved = _resolve_config(raw)
    return GatewayConfig(**resolved)


class ConfigWatcher:
    """Periodically checks config file mtime and triggers reload."""

    def __init__(
        self,
        path: str,
        callback: Callable[[GatewayConfig], Coroutine],
        interval: float = 30.0,
    ) -> None:
        self.path = os.path.expanduser(path)
        self.callback = callback
        self.interval = interval
        self._mtime: float = 0.0
        self._task: Optional[asyncio.Task] = None

    async def _poll(self) -> None:
        try:
            current = os.path.getmtime(self.path)
        except FileNotFoundError:
            current = 0.0

        self._mtime = current

        while True:
            await asyncio.sleep(self.interval)
            try:
                current = os.path.getmtime(self.path)
            except FileNotFoundError:
                continue

            if current > self._mtime:
                self._mtime = current
                try:
                    config = load_config(self.path)
                    await self.callback(config)
                except Exception as exc:
                    # Log but don't crash the watcher
                    print(f"[config] Reload failed: {exc}")

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
