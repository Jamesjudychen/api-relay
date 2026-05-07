"""Authentication middleware — Bearer token validation."""

from __future__ import annotations

from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from api_relay.auth import authenticate

if TYPE_CHECKING:
    pass


PUBLIC_PATHS = {"/health", "/admin/health"}


class AuthMiddleware(BaseHTTPMiddleware):
    """Validates Bearer tokens against the database on every proxied request.

    Public paths (/health) are exempted.  Attaches the key record to
    request.state.api_key on success.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ):
        # Skip auth for public paths
        if request.url.path in PUBLIC_PATHS:
            return await call_next(request)

        # Extract Bearer token
        auth_header = request.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"error": "Missing or malformed Authorization header"},
            )

        token = auth_header[len("Bearer "):].strip()
        if not token:
            return JSONResponse(
                status_code=401,
                content={"error": "Empty token"},
            )

        # Authenticate
        key_record = await authenticate(token)
        if key_record is None:
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid or expired API key"},
            )

        # Attach to request state for downstream use
        request.state.api_key = key_record
        return await call_next(request)
