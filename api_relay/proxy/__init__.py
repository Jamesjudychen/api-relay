"""Proxy module — HTTP forwarding and streaming response support."""

from __future__ import annotations

from api_relay.proxy.forwarder import proxy_request
from api_relay.proxy.stream import proxy_streaming_response, is_streaming_request

__all__ = ["proxy_request", "proxy_streaming_response", "is_streaming_request"]
