"""Logging middleware — records request/response metadata to SQLite."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

import api_relay.app_state as app_state
from api_relay.db import flush_logs, queue_log


class LoggingMiddleware(BaseHTTPMiddleware):
    """Records request/response metadata to the request_logs table."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._batch_size = 0

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        start_time_unix = time.monotonic()
        start_time_str = time.strftime(
            "%Y-%m-%d %H:%M:%S", time.gmtime()
        )

        body_bytes = await request.body()
        body_size = len(body_bytes) if body_bytes else 0

        response = await call_next(request)

        latency_ms = int((time.monotonic() - start_time_unix) * 1000)

        key_record: Optional[Dict[str, Any]] = getattr(
            request.state, "api_key", None
        )

        log_entry: Dict[str, Any] = {
            "timestamp": start_time_str,
            "method": request.method,
            "path": request.url.path,
            "query_string": str(request.url.query) or None,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
            "api_key_id": key_record.get("id") if key_record else None,
            "api_key_name": key_record.get("name") if key_record else None,
            "upstream_url": getattr(request.state, "upstream_url", None),
            "provider_name": getattr(request.state, "provider_name", None),
            "request_headers": None,
            "response_headers": None,
            "request_body_size": body_size,
            "response_body_size": None,
            "client_ip": request.client.host if request.client else None,
            "error": None,
        }

        queue_log(log_entry)
        self._batch_size += 1

        if self._batch_size >= app_state.config.batch_log_flush_count:
            self._batch_size = 0
            asyncio.ensure_future(flush_logs())

        return response

    @staticmethod
    async def start_flush_loop() -> None:
        """Background task: periodically flush the log buffer."""
        while True:
            await asyncio.sleep(app_state.config.batch_log_flush_interval)
            try:
                await flush_logs()
            except Exception:
                pass
