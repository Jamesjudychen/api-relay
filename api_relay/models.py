"""Shared Pydantic models for the API gateway."""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ProxyRequest(BaseModel):
    method: str
    path: str
    headers: Dict[str, str] = {}
    query_params: Dict[str, str] = {}
    body: Optional[Any] = None
    client_ip: str = ""


class ProxyResponse(BaseModel):
    status_code: int
    headers: Dict[str, str]
    body: Any


class RouteMatch(BaseModel):
    upstream_url: str
    extra_headers: Dict[str, str] = {}
    timeout: float = 30.0


class HealthStatus(BaseModel):
    status: str = "ok"
    version: str = "0.1.0"
    uptime_seconds: float = 0.0
    active_keys: int = 0
    routes_loaded: int = 0


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
