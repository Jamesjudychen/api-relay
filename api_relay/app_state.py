"""Shared application state — avoids circular imports between main.py and middleware."""

from __future__ import annotations

from typing import Optional

from api_relay.config import GatewayConfig
from api_relay.routing import RouterEngine

config: GatewayConfig = None  # type: ignore[assignment]
router_engine: Optional[RouterEngine] = None
