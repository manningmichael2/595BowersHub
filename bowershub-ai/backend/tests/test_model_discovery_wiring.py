"""Tests for the discovery wiring (spec: dynamic-model-discovery, Task 6):
the admin refresh endpoint + DB-driven discovery config. Covers R2.3 (admin
trigger, require_admin), R2.2 (interval floor + enabled lever)."""

from __future__ import annotations

import asyncpg
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.config import Config
from backend.database import init_pool, run_migrations
from backend.middleware.auth import require_admin
from backend.routers.admin import router as admin_router
from backend.services.model_catalog import RefreshSummary, get_discovery_config

pytestmark = pytest.mark.asyncio


class _FakeRefresh:
    def __init__(self):
        self.calls = 0
    async def refresh(self, *, trigger="scheduled"):
        self.calls += 1
        self.last_trigger = trigger
        return RefreshSummary(added=2, reactivated=1, deactivated=0, price_flagged=2, complete=True)


def _app(catalog_refresh=None) -> FastAPI:
    app = FastAPI()
    app.state.config = Config(
        ANTHROPIC_API_KEY="test", DB_HOST="x", DB_PORT=5432, DB_NAME="x",
        DB_USER="x", DB_PASSWORD="x", JWT_SECRET="test", N8N_BASE="http://localhost:5678",
    )
    app.include_router(admin_router)
    if catalog_refresh is not None:
        app.state.catalog_refresh = catalog_refresh
    return app


async def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_admin_refresh_requires_admin():
    app = _app(_FakeRefresh())          # no auth override → require_admin rejects
    async with await _client(app) as c:
        resp = await c.post("/api/admin/models/refresh")
    assert resp.status_code in (401, 403)


async def test_admin_refresh_invokes_refresh_as_admin():
    fake = _FakeRefresh()
    app = _app(fake)
    app.dependency_overrides[require_admin] = lambda: {"id": 1, "role": "admin"}
    async with await _client(app) as c:
        resp = await c.post("/api/admin/models/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"added": 2, "reactivated": 1, "deactivated": 0, "price_flagged": 2, "complete": True}
    assert fake.calls == 1 and fake.last_trigger == "admin"   # admin trigger, regardless of the enabled lever


async def test_admin_refresh_503_when_uninitialized():
    app = _app(catalog_refresh=None)    # app.state.catalog_refresh missing
    app.dependency_overrides[require_admin] = lambda: {"id": 1, "role": "admin"}
    async with await _client(app) as c:
        resp = await c.post("/api/admin/models/refresh")
    assert resp.status_code == 503


# --- DB-driven config (R2.2): interval floor + enabled lever ---------------
async def _apply_migrations(db_name, db_settings) -> asyncpg.Pool:
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test", N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    await run_migrations(pool)
    return pool


async def test_discovery_config_clamps_interval_and_reads_enabled(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        # defaults from 0005
        interval, enabled = await get_discovery_config(pool)
        assert interval == 24 and enabled is True
        # a sub-floor interval is clamped to the 6h floor; disable the lever
        async with pool.acquire() as c:
            await c.execute("UPDATE public.bh_platform_settings SET value_json='{\"hours\": 1}'::jsonb WHERE key='model_discovery_interval_hours'")
            await c.execute("UPDATE public.bh_platform_settings SET value_json='{\"enabled\": false}'::jsonb WHERE key='model_discovery_enabled'")
        interval, enabled = await get_discovery_config(pool)
        assert interval == 6 and enabled is False
    finally:
        await pool.close()
