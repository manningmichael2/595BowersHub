"""Task 9 — per-user feature access (R5.2/R5.3).

T-FEATURE-1: an admin disables Finance for a member → /api/finance/* returns 403
  AND /me-style effective access marks finance not-permitted; re-enabling restores
  both — with no restart (authz.reload after the write).
T-FLOOR-1: a per-user override can't grant the floored 'database' feature to a
  member — the PUT is rejected (400) and resolve still denies (403).
Plus the resolver precedence as a unit (restrict-only; floor unconditional).
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
        JWT_SECRET="test-secret-for-user-feature-access",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.admin import router as admin
    from backend.routers.finance_review import router as review
    from backend.routers.db_browser import router as db_browser
    for r in (admin, review, db_browser):
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
    headers = {
        "admin": {"Authorization": "Bearer " + auth.generate_access_token(admin_id, "a@t", "admin")},
        "member": {"Authorization": "Bearer " + auth.generate_access_token(member_id, "m@t", "member")},
    }
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "member_id": member_id, "admin_id": admin_id,
                   "headers": headers}
        finally:
            await close_pool()


# --- T-FEATURE-1 ------------------------------------------------------------
async def test_disable_finance_for_member_blocks_reads_then_restore(env):
    read_url = "/api/finance/categories"
    # Baseline: member can read finance.
    assert (await env["client"].get(read_url, headers=env["headers"]["member"])).status_code == 200

    # Admin disables the finance feature for the member.
    r = await env["client"].put(f"/api/admin/users/{env['member_id']}/features/finance",
                                json={"enabled": False}, headers=env["headers"]["admin"])
    assert r.status_code == 200
    # Now /api/finance/* is 403 for that member (no restart) — feature-disable
    # subtracts even from a capability their role would otherwise satisfy.
    assert (await env["client"].get(read_url, headers=env["headers"]["member"])).status_code == 403
    # The admin is unaffected.
    assert (await env["client"].get(read_url, headers=env["headers"]["admin"])).status_code == 200

    # Re-enable → access restored immediately.
    r2 = await env["client"].put(f"/api/admin/users/{env['member_id']}/features/finance",
                                 json={"enabled": True}, headers=env["headers"]["admin"])
    assert r2.status_code == 200
    assert (await env["client"].get(read_url, headers=env["headers"]["member"])).status_code == 200


async def test_get_user_features_reflects_override(env):
    await env["client"].put(f"/api/admin/users/{env['member_id']}/features/finance",
                            json={"enabled": False}, headers=env["headers"]["admin"])
    resp = await env["client"].get(f"/api/admin/users/{env['member_id']}/features",
                                   headers=env["headers"]["admin"])
    assert resp.status_code == 200
    by_key = {f["feature_key"]: f for f in resp.json()}
    assert by_key["finance"]["enabled"] is False
    assert by_key["database"]["enabled"] is True   # untouched → default enabled


# --- T-FLOOR-1 --------------------------------------------------------------
async def test_cannot_grant_floored_database_to_member(env):
    # PUT enabling the floored 'database' feature for a member is rejected.
    r = await env["client"].put(f"/api/admin/users/{env['member_id']}/features/database",
                                json={"enabled": True}, headers=env["headers"]["admin"])
    assert r.status_code == 400
    # And even if a row existed, resolve() still denies db.browser to a member.
    member = {"id": env["member_id"], "role": "member"}
    assert authz.resolve(member, "db.browser") is False


async def test_floored_feature_can_still_be_disabled(env):
    # Disabling (restricting) a floored feature is allowed (it only subtracts).
    r = await env["client"].put(f"/api/admin/users/{env['member_id']}/features/database",
                                json={"enabled": False}, headers=env["headers"]["admin"])
    assert r.status_code == 200


# --- resolver precedence (unit) ---------------------------------------------
async def test_resolve_precedence_unit(env):
    member = {"id": env["member_id"], "role": "member"}
    admin = {"id": env["admin_id"], "role": "admin"}
    # member satisfies finance.write by rank...
    assert authz.resolve(member, "finance.write") is True
    # ...until finance is disabled for them.
    async with env["pool"].acquire() as conn:
        await conn.execute(
            "INSERT INTO public.bh_user_feature_access (user_id, feature_key, enabled, set_by) "
            "VALUES ($1,'finance',false,$2)", env["member_id"], env["admin_id"])
    await authz.reload()
    assert authz.resolve(member, "finance.write") is False
    # The floor on database denies a member unconditionally; admin always passes.
    assert authz.resolve(member, "db.browser") is False
    assert authz.resolve(admin, "db.browser") is True
    assert authz.resolve(admin, "finance.write") is True
