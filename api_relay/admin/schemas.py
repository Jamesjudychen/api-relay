"""Pydantic request/response schemas for the admin API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ApiKeyCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    role: str = Field(default="user", pattern="^(admin|user)$")
    rate_limit_requests: Optional[int] = Field(None, ge=1)
    rate_limit_window: Optional[int] = Field(None, ge=1)
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None


class ApiKeyCreateResponse(BaseModel):
    id: int
    key: str  # raw key, only shown once at creation
    name: str
    role: str
    key_prefix: str


class ApiKeyResponse(BaseModel):
    id: int
    key_prefix: str
    name: str
    role: str
    is_active: bool
    rate_limit_requests: Optional[int] = None
    rate_limit_window: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None
    created_at: str
    updated_at: str


class ApiKeyUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    role: Optional[str] = Field(None, pattern="^(admin|user)$")
    is_active: Optional[bool] = None
    rate_limit_requests: Optional[int] = Field(None, ge=1)
    rate_limit_window: Optional[int] = Field(None, ge=1)
    metadata: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int
    total_pages: int


class StatsResponse(BaseModel):
    total_requests: int = 0
    avg_latency_ms: Optional[float] = None
    max_latency_ms: Optional[float] = None
    success_count: int = 0
    error_count: int = 0
