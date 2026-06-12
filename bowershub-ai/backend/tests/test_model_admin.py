"""Admin curation tests (spec: dynamic-model-discovery, Task 10) — R5.1.

Exercises the admin model endpoints against an ephemeral Postgres: typed-field
edits + unknown-field rejection, the alias-repoint endpoint (valid / inactive /
missing), roles in the GET, and require_admin RBAC."""

from __future__ import annotations

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.config import Config
from backend.database import init_pool, run_migrations
from backend.middleware.auth import require_admin
from backend.routers.admin import router as admin_router

pytestmark = pytest.mark.asyncio


def _config(db_name, db_settings) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test", N8N_BASE="http://localhost:5678",
    )


def _app(config, *, as_admin=True) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    app.include_router(admin_router)
    if as_admin:
        app.dependency_overrides[require_admin] = lambda: {"id": 1, "role": "admin"}
    return app


@pytest_asyncio.fixture
async def env(fresh_db, db_settings):
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)          # sets the global pool get_pool() returns
    await run_migrations(pool)
    try:
        yield config, pool
    finally:
        await pool.close()


def _client(app):
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_patch_edits_typed_fields_and_rejects_unknown(env):
    config, pool = env
    app = _app(config)
    mid = await pool.fetchval("SELECT id FROM public.bh_model_rates WHERE model_id='claude-sonnet-4-6'")
    async with _client(app) as c:
        ok = await c.patch(f"/api/admin/models/{mid}",
                           json={"input_cost_per_mtok": 4.5, "needs_price_confirmation": True, "is_active": True})
        assert ok.status_code == 200 and ok.json()["needs_price_confirmation"] is True
        bad = await c.patch(f"/api/admin/models/{mid}", json={"totally_bogus": 1})
        assert bad.status_code == 422        # extra=forbid closed whitelist
    assert float(await pool.fetchval("SELECT input_cost_per_mtok FROM public.bh_model_rates WHERE id=$1", mid)) == 4.5


async def test_get_models_includes_roles(env):
    config, pool = env
    app = _app(config)
    async with _client(app) as c:
        rows = (await c.get("/api/admin/models")).json()
    sonnet = next(r for r in rows if r["model_id"] == "claude-sonnet-4-6")
    assert "chat" in sonnet["roles"]
    bedrock = next(r for r in rows if r["model_id"] == "us.anthropic.claude-sonnet-4-5-v1:0")
    assert bedrock["roles"] == []           # not an alias target


async def test_repoint_alias_valid_inactive_and_missing(env):
    config, pool = env
    app = _app(config)
    async with _client(app) as c:
        # valid repoint: chat -> haiku model
        ok = await c.put("/api/admin/models/aliases/chat", json={"model_id": "claude-haiku-4-5-20251001"})
        assert ok.status_code == 200 and ok.json()["model_id"] == "claude-haiku-4-5-20251001"
        assert await pool.fetchval("SELECT model_id FROM public.bh_model_aliases WHERE role='chat'") == "claude-haiku-4-5-20251001"
        # missing model -> 404
        assert (await c.put("/api/admin/models/aliases/deep", json={"model_id": "nope-9"})).status_code == 404
        # inactive model -> 400
        await pool.execute("UPDATE public.bh_model_rates SET is_active=false WHERE model_id='claude-opus-4-5'")
        bad = await c.put("/api/admin/models/aliases/deep", json={"model_id": "claude-opus-4-5"})
        assert bad.status_code == 400


async def test_admin_endpoints_require_admin(env):
    config, pool = env
    app = _app(config, as_admin=False)      # no override → real require_admin
    async with _client(app) as c:
        assert (await c.get("/api/admin/models")).status_code in (401, 403)
        assert (await c.put("/api/admin/models/aliases/chat", json={"model_id": "x"})).status_code in (401, 403)
