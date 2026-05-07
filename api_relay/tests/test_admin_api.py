"""Tests for the admin API endpoints."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    """Test the public health endpoint."""
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "uptime_seconds" in data


@pytest.mark.asyncio
async def test_create_api_key(client: AsyncClient, admin_key: str):
    """Test creating a new API key via the admin API."""
    resp = await client.post(
        "/admin/api-keys",
        json={"name": "New Test Key", "role": "user"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "New Test Key"
    assert data["role"] == "user"
    assert data["key"].startswith("ag_")
    assert "id" in data


@pytest.mark.asyncio
async def test_list_api_keys(client: AsyncClient, admin_key: str):
    """Test listing API keys."""
    resp = await client.get(
        "/admin/api-keys",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert data["page"] == 1


@pytest.mark.asyncio
async def test_get_api_key(client: AsyncClient, admin_key: str):
    """Test getting a single API key details."""
    # First create a key
    create_resp = await client.post(
        "/admin/api-keys",
        json={"name": "Key To Fetch", "role": "user"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    key_id = create_resp.json()["id"]

    # Fetch it
    resp = await client.get(
        f"/admin/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Key To Fetch"
    assert data["id"] == key_id


@pytest.mark.asyncio
async def test_update_api_key(client: AsyncClient, admin_key: str):
    """Test updating an API key."""
    create_resp = await client.post(
        "/admin/api-keys",
        json={"name": "Original Name", "role": "user"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    key_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/admin/api-keys/{key_id}",
        json={"name": "Updated Name"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Name"


@pytest.mark.asyncio
async def test_delete_api_key(client: AsyncClient, admin_key: str):
    """Test soft-deleting an API key."""
    create_resp = await client.post(
        "/admin/api-keys",
        json={"name": "Key To Delete", "role": "user"},
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    key_id = create_resp.json()["id"]

    resp = await client.delete(
        f"/admin/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 204

    # Verify it's deactivated
    get_resp = await client.get(
        f"/admin/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert get_resp.json()["is_active"] is False


@pytest.mark.asyncio
async def test_admin_requires_auth(client: AsyncClient):
    """Test that admin endpoints reject unauthenticated requests."""
    resp = await client.get("/admin/api-keys")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_user_cannot_access_admin(client: AsyncClient, user_key: str):
    """Test that non-admin keys cannot access admin endpoints."""
    resp = await client.get(
        "/admin/api-keys",
        headers={"Authorization": f"Bearer {user_key}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_stats_endpoint(client: AsyncClient, admin_key: str):
    """Test the stats endpoint."""
    resp = await client.get(
        "/admin/stats",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "total_requests" in data


@pytest.mark.asyncio
async def test_create_key_with_rate_limit_override(client: AsyncClient, admin_key: str):
    """Test creating a key with custom rate limits."""
    resp = await client.post(
        "/admin/api-keys",
        json={
            "name": "Rate Limited Key",
            "role": "user",
            "rate_limit_requests": 10,
            "rate_limit_window": 5,
        },
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Rate Limited Key"

    # Verify the overrides were saved
    key_id = data["id"]
    get_resp = await client.get(
        f"/admin/api-keys/{key_id}",
        headers={"Authorization": f"Bearer {admin_key}"},
    )
    assert get_resp.json()["rate_limit_requests"] == 10
    assert get_resp.json()["rate_limit_window"] == 5
