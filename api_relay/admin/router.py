"""Admin REST API router — API key management and statistics."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api_relay.admin.schemas import (
    ApiKeyCreateRequest,
    ApiKeyCreateResponse,
    ApiKeyResponse,
    ApiKeyUpdateRequest,
    PaginatedResponse,
    StatsResponse,
)
from api_relay.auth import authenticate, create_key_record
from api_relay.db import (
    count_active_keys,
    delete_api_key,
    get_api_key_by_id,
    get_request_stats,
    list_api_keys,
    update_api_key,
)

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(request: Request) -> None:
    """Dependency: ensure the request has a valid admin API key."""
    key_record = getattr(request.state, "api_key", None)
    if key_record is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    if key_record.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")


def _to_api_key_response(row: dict) -> ApiKeyResponse:
    # Parse metadata from JSON string if needed
    metadata = row.get("metadata")
    if isinstance(metadata, str):
        import json
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    return ApiKeyResponse(
        id=row["id"],
        key_prefix=row["key_prefix"],
        name=row["name"],
        role=row["role"],
        is_active=bool(row["is_active"]),
        rate_limit_requests=row.get("rate_limit_requests"),
        rate_limit_window=row.get("rate_limit_window"),
        metadata=metadata,
        expires_at=row.get("expires_at"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


@router.get("/api-keys", response_model=PaginatedResponse)
async def list_keys(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    include_inactive: bool = Query(False),
    _: None = Depends(require_admin),
):
    """List all API keys with pagination."""
    keys, total = await list_api_keys(
        page=page, page_size=page_size, include_inactive=include_inactive
    )
    return PaginatedResponse(
        items=[_to_api_key_response(k) for k in keys],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


@router.post("/api-keys", response_model=ApiKeyCreateResponse, status_code=201)
async def create_key(
    request: Request,
    body: ApiKeyCreateRequest,
    _: None = Depends(require_admin),
):
    """Create a new API key."""
    raw_key, row_id = await create_key_record(
        name=body.name,
        role=body.role,
        rate_limit_requests=body.rate_limit_requests,
        rate_limit_window=body.rate_limit_window,
        metadata=body.metadata,
        expires_at=body.expires_at,
    )
    return ApiKeyCreateResponse(
        id=row_id,
        key=raw_key,
        name=body.name,
        role=body.role,
        key_prefix=raw_key[:12],
    )


@router.get("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def get_key(
    request: Request,
    key_id: int,
    _: None = Depends(require_admin),
):
    """Get a single API key's details."""
    record = await get_api_key_by_id(key_id)
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found")
    return _to_api_key_response(record)


@router.patch("/api-keys/{key_id}", response_model=ApiKeyResponse)
async def update_key(
    request: Request,
    key_id: int,
    body: ApiKeyUpdateRequest,
    _: None = Depends(require_admin),
):
    """Update an API key's attributes."""
    update_data = body.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")

    success = await update_api_key(key_id, **update_data)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")

    record = await get_api_key_by_id(key_id)
    assert record is not None
    return _to_api_key_response(record)


@router.delete("/api-keys/{key_id}", status_code=204)
async def delete_key(
    request: Request,
    key_id: int,
    _: None = Depends(require_admin),
):
    """Soft-delete (deactivate) an API key."""
    success = await delete_api_key(key_id)
    if not success:
        raise HTTPException(status_code=404, detail="API key not found")


@router.get("/stats", response_model=StatsResponse)
async def get_stats(
    request: Request,
    since: Optional[str] = Query(None),
    _: None = Depends(require_admin),
):
    """Get aggregated request statistics."""
    stats = await get_request_stats(since=since)
    return StatsResponse(**stats)
