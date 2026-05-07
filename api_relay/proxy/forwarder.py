"""HTTP request forwarding via httpx."""

from __future__ import annotations

import json
from typing import AsyncIterator, Dict, Optional, Tuple

import httpx

# Headers that should not be forwarded to upstream servers
HOP_BY_HOP_HEADERS = {
    "host",
    "transfer-encoding",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "upgrade",
    "content-length",
}


def _clean_headers(headers: Dict[str, str]) -> Dict[str, str]:
    """Remove hop-by-hop headers and content-length (httpx sets it)."""
    return {
        k: v
        for k, v in headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }


async def proxy_request(
    method: str,
    url: str,
    headers: Dict[str, str],
    body: Optional[bytes],
    timeout: float = 30.0,
    extra_headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Dict[str, str], AsyncIterator[bytes] | bytes]:
    """Forward an HTTP request to an upstream server.

    Args:
        method: HTTP method.
        url: Full upstream URL.
        headers: Request headers to forward.
        body: Request body bytes.
        timeout: Upstream timeout in seconds.
        extra_headers: Additional headers to inject (from route rule).

    Returns:
        Tuple of (status_code, response_headers, response_body).
        response_body is an async iterator if streaming, or bytes otherwise.
    """
    clean_headers = _clean_headers(headers)

    # Inject extra headers from route rule
    if extra_headers:
        clean_headers.update(extra_headers)

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
    ) as client:
        req = client.build_request(method, url, headers=clean_headers, content=body)

        # Detect if the upstream is likely to stream
        accept = headers.get("accept", "")
        is_stream = "text/event-stream" in accept.lower()

        if is_stream:
            resp = await client.send(req, stream=True)
            return resp.status_code, dict(resp.headers), resp.aiter_bytes()
        else:
            resp = await client.send(req)
            return resp.status_code, dict(resp.headers), resp.content
