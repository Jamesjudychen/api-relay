"""Streaming response support — SSE forwarding via FastAPI StreamingResponse."""

from __future__ import annotations

import json
from typing import AsyncIterator, Dict, Optional

from fastapi import Request
from fastapi.responses import StreamingResponse


def is_streaming_request(request: Request) -> bool:
    """Detect if the client expects a streaming response."""
    accept = request.headers.get("accept", "").lower()
    if "text/event-stream" in accept:
        return True

    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = json.loads(request.body())
            if isinstance(body, dict) and body.get("stream", False):
                return True
        except (json.JSONDecodeError, RuntimeError):
            pass

    return False


def proxy_streaming_response(
    status_code: int,
    upstream_headers: Dict[str, str],
    upstream_body_iter: AsyncIterator[bytes],
) -> StreamingResponse:
    """Wrap an upstream streaming response into a FastAPI StreamingResponse.

    Args:
        status_code: HTTP status code from upstream.
        upstream_headers: Response headers from upstream.
        upstream_body_iter: Async iterator of bytes chunks.

    Returns:
        A FastAPI StreamingResponse.
    """
    filtered_headers = {
        k: v
        for k, v in upstream_headers.items()
        if k.lower() not in {"content-length", "transfer-encoding"}
    }

    return StreamingResponse(
        content=upstream_body_iter,
        status_code=status_code,
        headers=filtered_headers,
        media_type=upstream_headers.get("content-type", "application/octet-stream"),
    )
