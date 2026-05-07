"""FastAPI application — the main entry point for the API gateway."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from api_relay import __version__
from api_relay.admin.router import router as admin_router
from api_relay.config import ConfigWatcher, GatewayConfig, load_config
from api_relay.db import close_db, count_active_keys, flush_logs, init_db
from api_relay.middleware.auth import AuthMiddleware
from api_relay.middleware.logging import LoggingMiddleware
from api_relay.middleware.rate_limit import RateLimitMiddleware
from api_relay.models import ErrorResponse, HealthStatus
from api_relay.proxy import is_streaming_request, proxy_request, proxy_streaming_response
from api_relay.routing import RouterEngine

import api_relay.app_state as app_state


def _get_default_config_path() -> str:
    """Get the default configuration file path."""
    return os.environ.get(
        "API_RELAY_CONFIG",
        os.path.join(os.path.dirname(__file__), "api_relay.yaml"),
    )


# ─── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: setup on start, teardown on shutdown."""
    # Use app_state.config if pre-set (e.g., test fixtures), otherwise load from file
    if app_state.config is None:
        config_path = getattr(app.state, "_config_path", None) or _get_default_config_path()
        cfg = load_config(config_path)
    else:
        cfg = app_state.config
        config_path = getattr(app.state, "_config_path", None) or _get_default_config_path()

    app_state.config = cfg
    app_state.router_engine = RouterEngine(cfg)
    app.state.config = cfg

    # Init database
    await init_db(cfg.db_path)
    print(f"[db] Database initialized at {cfg.db_path}")

    # Seed bootstrap admin keys
    await _seed_keys(cfg)

    # Start config watcher
    async def on_reload(new_cfg: GatewayConfig) -> None:
        app_state.config = new_cfg
        app_state.router_engine = RouterEngine(new_cfg)
        app.state.config = new_cfg
        print(f"[config] Reloaded — {len(new_cfg.routes)} routes")

    watcher = ConfigWatcher(config_path, on_reload, cfg.config_reload_seconds)
    watcher.start()
    app.state.watcher = watcher

    # Start log flusher
    import asyncio

    async def log_flush_loop():
        while True:
            await asyncio.sleep(cfg.batch_log_flush_interval)
            try:
                await flush_logs()
            except Exception:
                pass

    app.state.log_flush_task = asyncio.create_task(log_flush_loop())

    print(f"[startup] API Relay v{__version__} ready on {cfg.host}:{cfg.port}")
    yield

    # Shutdown
    if hasattr(app.state, "watcher") and app.state.watcher:
        await app.state.watcher.stop()
    if hasattr(app.state, "log_flush_task") and app.state.log_flush_task:
        app.state.log_flush_task.cancel()
    await flush_logs()
    await close_db()
    print("[shutdown] API Relay stopped")


# ─── App creation ─────────────────────────────────────────────────────────────


def create_app(config_path: Optional[str] = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config_path: Optional explicit config path. Uses env var or default if not set.
    """
    app = FastAPI(
        title="API Relay",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # Store config path for lifespan to use
    if config_path:
        app.state._config_path = config_path

    # Register middleware (order: logging → rate_limit → auth)
    app.add_middleware(LoggingMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(AuthMiddleware)

    # Register routers
    app.include_router(admin_router)

    # Health endpoint
    @app.get("/health", tags=["system"])
    async def health():
        active = await count_active_keys()
        return HealthStatus(
            status="ok",
            version=__version__,
            uptime_seconds=time.time() - _start_time,
            active_keys=active,
            routes_loaded=len(app_state.config.routes) if app_state.config else 0,
        )

    # Catch-all proxy endpoint
    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    )
    async def proxy(request: Request, path: str):
        if app_state.config is None or app_state.router_engine is None:
            return JSONResponse(
                status_code=503,
                content={"error": "Gateway still initializing"},
            )

        full_path = f"/{path}"
        match = app_state.router_engine.match(
            method=request.method,
            path=full_path,
            headers=dict(request.headers),
            body=await _json_body(request),
        )

        if match is None:
            return JSONResponse(
                status_code=502,
                content=ErrorResponse(
                    error="No matching route",
                    detail=f"No route rule matched {request.method} {full_path}",
                ).model_dump(),
            )

        request.state.upstream_url = match.upstream_url
        request.state.provider_name = _guess_provider(match.upstream_url)

        stream = is_streaming_request(request) or _is_stream_upstream(match.upstream_url)

        try:
            status, resp_headers, body = await proxy_request(
                method=request.method,
                url=match.upstream_url,
                headers=dict(request.headers),
                body=await request.body(),
                timeout=match.timeout,
                extra_headers=match.extra_headers,
            )
        except Exception as exc:
            return JSONResponse(
                status_code=502,
                content=ErrorResponse(
                    error="Upstream request failed",
                    detail=str(exc),
                ).model_dump(),
            )

        if stream:
            return proxy_streaming_response(status, resp_headers, body)

        return Response(content=body, status_code=status, headers=resp_headers)

    return app


def _guess_provider(url: str) -> str:
    """Guess provider name from upstream URL."""
    known = {
        "openai.com": "openai",
        "anthropic.com": "anthropic",
        "openrouter.ai": "openrouter",
        "googleapis.com": "google",
        "deepseek.com": "deepseek",
        "mistral.ai": "mistral",
    }
    for domain, name in known.items():
        if domain in url:
            return name
    return "custom"


def _is_stream_upstream(url: str) -> bool:
    """Heuristic: check if the upstream URL is likely a streaming endpoint."""
    stream_paths = ("/chat/completions", "/messages", "/completions", "/stream")
    return any(p in url for p in stream_paths)


async def _json_body(request: Request) -> Optional[Dict[str, Any]]:
    """Try to parse request body as JSON. Returns None on failure."""
    try:
        return await request.json()
    except Exception:
        return None


async def _seed_keys(cfg: GatewayConfig) -> None:
    """Seed bootstrap API keys into the database."""
    from api_relay.auth import authenticate
    from api_relay.db import create_api_key

    import hashlib

    for raw_key in cfg.api_keys.admin_keys:
        existing = await authenticate(raw_key)
        if existing is None:
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            key_prefix = raw_key[:12]
            await create_api_key(
                key_hash=key_hash,
                key_prefix=key_prefix,
                name=f"Bootstrap admin ({key_prefix}...)",
                role="admin",
            )
            print(f"[auth] Seeded admin key: {key_prefix}...")

    for raw_key in cfg.api_keys.user_keys:
        existing = await authenticate(raw_key)
        if existing is None:
            key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
            key_prefix = raw_key[:12]
            await create_api_key(
                key_hash=key_hash,
                key_prefix=key_prefix,
                name=f"Bootstrap user ({key_prefix}...)",
                role="user",
            )
            print(f"[auth] Seeded user key: {key_prefix}...")


# ─── CLI ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """CLI entry point: parse args, configure, and start uvicorn."""
    import argparse

    parser = argparse.ArgumentParser(description="API Relay")
    parser.add_argument("--config", "-c", default=None, help="Config YAML path")
    parser.add_argument("--host", "-H", default=None, help="Bind address")
    parser.add_argument("--port", "-P", type=int, default=None, help="Bind port")
    parser.add_argument("--reload", action="store_true", help="Enable uvicorn hot-reload")
    args = parser.parse_args()

    config_path = args.config or _get_default_config_path()
    cfg = load_config(config_path)

    host = args.host or cfg.host
    port = args.port or cfg.port

    print(f"[startup] API Relay v{__version__}")
    print(f"[startup] Config: {config_path}")
    print(f"[startup] Listening on {host}:{port}")

    uvicorn.run(
        "api_relay.main:app",
        host=host,
        port=port,
        log_level=cfg.log_level.lower(),
        reload=args.reload,
    )


# ─── Module-level app instance ────────────────────────────────────────────────

_start_time: float = time.time()
app = create_app()
