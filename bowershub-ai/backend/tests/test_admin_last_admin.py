"""T-ADMIN-1 — user management + last-admin invariant (R2.1 / R2.1a).

- A demote OR deactivate that would leave zero active admins is rejected (409),
  for both the self-demote and other-demote paths.
- Two concurrent last-admin demotions serialize: exactly one succeeds (the
  FOR UPDATE lock prevents both observing "1 remaining admin").
- Role validation rejects an unknown role (400); a normal demote with a spare
  admin present succeeds.
"""

from __future__ import annotations

import asyncio
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
        JWT_SECRET="test-secret-for-last-admin-invariant",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.admin import router as admin
    app.include_router(admin)
    return app


async def _mk_admin(conn, email) -> int:
    return await conn.fetchval(
        "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
        "VALUES ($1,'x','A','admin') RETURNING id", email)


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    async with pool.acquire() as conn:
        a1 = await _mk_admin(conn, "a1@t")
    token = AuthService(pool, config).generate_access_token(a1, "a1@t", "admin")
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "a1": a1,
                   "auth": {"Authorization": f"Bearer {token}"}}
        finally:
            await close_pool()


async def test_demote_last_admin_self_rejected_409(env):
    r = await env["client"].patch(f"/api/admin/users/{env['a1']}",
                                  json={"role": "member"}, headers=env["auth"])
    assert r.status_code == 409
    async with env["pool"].acquire() as conn:
        role = await conn.fetchval("SELECT role FROM public.bh_users WHERE id=$1", env["a1"])
    assert role == "admin"  # rolled back


async def test_deactivate_last_admin_rejected_409(env):
    r = await env["client"].patch(f"/api/admin/users/{env['a1']}",
                                  json={"is_active": False}, headers=env["auth"])
    assert r.status_code == 409
    async with env["pool"].acquire() as conn:
        active = await conn.fetchval("SELECT is_active FROM public.bh_users WHERE id=$1", env["a1"])
    assert active is True


async def test_demote_other_admin_allowed_when_spare_present(env):
    async with env["pool"].acquire() as conn:
        a2 = await _mk_admin(conn, "a2@t")
    # Two admins now → demoting a2 leaves a1 → allowed.
    r = await env["client"].patch(f"/api/admin/users/{a2}",
                                  json={"role": "member"}, headers=env["auth"])
    assert r.status_code == 200 and r.json()["role"] == "member"
    # ...but demoting the last remaining admin (a1) is then rejected.
    r2 = await env["client"].patch(f"/api/admin/users/{env['a1']}",
                                   json={"role": "viewer"}, headers=env["auth"])
    assert r2.status_code == 409


async def test_invalid_role_rejected_400(env):
    r = await env["client"].patch(f"/api/admin/users/{env['a1']}",
                                  json={"role": "superuser"}, headers=env["auth"])
    assert r.status_code == 400


async def test_concurrent_last_two_admin_demotions_exactly_one_succeeds(env):
    async with env["pool"].acquire() as conn:
        a2 = await _mk_admin(conn, "a2@t")
    # Fire both demotions concurrently; the FOR UPDATE lock must serialize them so
    # exactly one wins and at least one admin always remains.
    r1, r2 = await asyncio.gather(
        env["client"].patch(f"/api/admin/users/{env['a1']}", json={"role": "member"}, headers=env["auth"]),
        env["client"].patch(f"/api/admin/users/{a2}", json={"role": "member"}, headers=env["auth"]),
    )
    codes = sorted([r1.status_code, r2.status_code])
    assert codes == [200, 409], codes
    async with env["pool"].acquire() as conn:
        remaining = await conn.fetchval(
            "SELECT count(*) FROM public.bh_users WHERE role='admin' AND is_active")
    assert remaining == 1
