"""Rate limiting middleware — sliding window counter per key or IP."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

import api_relay.app_state as app_state
from api_relay.rate_limit import SlidingWindowCounter

PUBLIC_PATHS = {"/health", "/admin/health"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Applies rate limiting per API key (or per IP for unauthenticated)."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._counter = SlidingWindowCounter()

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        key_record = getattr(request.state, "api_key", None)

        if key_record:
            limit = key_record.get("rate_limit_requests") or app_state.config.default_rate_limit.requests
            window = key_record.get("rate_limit_window") or app_state.config.default_rate_limit.window_seconds
            partition_key = f"key:{key_record['key_hash']}"
        else:
            limit = app_state.config.ip_rate_limit.requests
            window = app_state.config.ip_rate_limit.window_seconds
            partition_key = f"ip:{request.client.host}" if request.client else "ip:unknown"

        allowed = await self._counter.check_and_increment(
            key=partition_key, limit=limit, window=window
        )

        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Try again later."},
                headers={"Retry-After": str(window)},
            )

        request.state.rate_limit_key = partition_key
        return await call_next(request)
