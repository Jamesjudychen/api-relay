"""Fixtures and test helpers for api_relay tests."""

from __future__ import annotations

import asyncio
import os
import tempfile
from typing import Any, AsyncGenerator, Dict

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from api_relay import app_state
from api_relay.config import GatewayConfig, RouteRule
from api_relay.db import DB, init_db
from api_relay.main import create_app
from api_relay.routing import RouterEngine


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async tests."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    """Create a temporary SQLite database for each test."""
    fd, path = tempfile.mkstemp(suffix=".db")

    await init_db(path)

    yield

    # Teardown
    if DB is not None:
        await DB.close()

    os.close(fd)
    os.unlink(path)


@pytest_asyncio.fixture(autouse=True)
async def setup_app_state():
    """Set up global app state for middleware to reference."""
    cfg = GatewayConfig(
        host="127.0.0.1",
        port=9000,
        db_path=":memory:",
        routes=[
            RouteRule(
                name="test-route",
                match_type="path_prefix",
                match_value="/test",
                target_url="https://httpbin.org",
                strip_prefix=True,
                timeout_seconds=10,
            ),
        ],
        api_keys={"admin_keys": ["ag_test_admin_key_change_me"], "user_keys": []},
    )
    app_state.config = cfg
    app_state.router_engine = RouterEngine(cfg)
    yield
    app_state.config = None  # type: ignore[assignment]
    app_state.router_engine = None


@pytest_asyncio.fixture
async def app():
    """Create a clean FastAPI app instance for testing."""
    application = create_app()
    async with LifespanManager(application) as manager:
        yield manager.app


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Provide an async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def admin_key(client: AsyncClient) -> str:
    """Create an admin API key via the DB directly and return it."""
    from api_relay.auth import create_key_record

    raw, _ = await create_key_record(
        name="Test Admin",
        role="admin",
    )
    return raw


@pytest_asyncio.fixture
async def user_key(client: AsyncClient) -> str:
    """Create a user API key and return it."""
    from api_relay.auth import create_key_record

    raw, _ = await create_key_record(
        name="Test User",
        role="user",
    )
    return raw
