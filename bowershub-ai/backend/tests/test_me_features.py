"""Task 10 (backend) — effective access + cosmetic self-hide.

- GET /api/me/features is the server-authoritative payload (role, capabilities,
  features[].permitted), reflecting per-user feature disables.
- PUT /api/me/settings/nav stores hidden_nav, validated to permitted features,
  and is purely cosmetic: T-COSMETIC-1 — a self-hidden Finance is still 200 on a
  direct GET, and another user's nav is unaffected.
"""

from __future__ import annotations

from typing import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import authz
from backend.services.auth import AuthService


pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-me-features",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.me import router as me
    from backend.routers.admin import router as admin
    from backend.routers.finance_review import router as review
    for r in (me, admin, review):
        app.include_router(r)
    return app


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    auth = AuthService(pool, config)
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('a@t','x','A','admin') RETURNING id")
        member_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t','x','M','member') RETURNING id")
        other_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('o@t','x','O','member') RETURNING id")
    headers = {
        "admin": {"Authorization": "Bearer " + auth.generate_access_token(admin_id, "a@t", "admin")},
        "member": {"Authorization": "Bearer " + auth.generate_access_token(member_id, "m@t", "member")},
        "other": {"Authorization": "Bearer " + auth.generate_access_token(other_id, "o@t", "member")},
    }
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "headers": headers,
                   "member_id": member_id, "other_id": other_id}
        finally:
            await close_pool()


async def test_me_features_shape_and_permissions(env):
    r = await env["client"].get("/api/me/features", headers=env["headers"]["member"])
    assert r.status_code == 200
    body = r.json()
    assert body["role"] == "member"
    assert "finance.write" in body["capabilities"]   # member resolves finance.write
    feats = {f["key"]: f for f in body["features"]}
    assert feats["finance"]["permitted"] is True
    assert feats["database"]["permitted"] is False   # admin-floored
    assert feats["finance"]["routes"] == ["/finance"]  # jsonb parsed to a list


async def test_me_features_reflects_disable(env):
    await env["client"].put(f"/api/admin/users/{env['member_id']}/features/finance",
                            json={"enabled": False}, headers=env["headers"]["admin"])
    r = await env["client"].get("/api/me/features", headers=env["headers"]["member"])
    feats = {f["key"]: f for f in r.json()["features"]}
    assert feats["finance"]["permitted"] is False


async def test_self_hide_is_cosmetic_only(env):
    # Member hides Finance from their own nav.
    r = await env["client"].put("/api/me/settings/nav",
                                json={"hidden": ["finance"]}, headers=env["headers"]["member"])
    assert r.status_code == 200 and r.json()["hidden_nav"] == ["finance"]
    # T-COSMETIC-1: the route is STILL reachable (200), proving it's display-only.
    assert (await env["client"].get("/api/finance/categories",
                                    headers=env["headers"]["member"])).status_code == 200
    # Persisted to settings_json.
    async with env["pool"].acquire() as conn:
        sj = await conn.fetchval("SELECT settings_json FROM public.bh_users WHERE id=$1", env["member_id"])
    assert sj["hidden_nav"] == ["finance"]
    # Another user's nav is unaffected.
    async with env["pool"].acquire() as conn:
        other_sj = await conn.fetchval("SELECT settings_json FROM public.bh_users WHERE id=$1", env["other_id"])
    assert not other_sj or "hidden_nav" not in other_sj


async def test_self_hide_drops_non_permitted_features(env):
    # A member can't hide 'database' (not permitted) — it's filtered out.
    r = await env["client"].put("/api/me/settings/nav",
                                json={"hidden": ["finance", "database"]}, headers=env["headers"]["member"])
    assert r.status_code == 200
    assert r.json()["hidden_nav"] == ["finance"]
