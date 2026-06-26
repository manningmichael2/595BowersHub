"""Task 7 — provisioning hardening (R2.2–R2.6).

- invite revoke prevents register (R2.2)
- admin reset-link rotates a user's password (R2.4)
- password policy rejects < 10 and common passwords, on register AND reset (R2.3)
- a newly-registered member lands in the default workspace (R2.5)
- first-admin display_name comes from env / email local-part, not a hardcode (R2.6)
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

_STRONG = "Tr0ub4dour-River-92"   # passes policy everywhere in this file


def _config(db_name: str, db_settings: dict, **extra) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-provisioning-hardening-tests",
        N8N_BASE="http://localhost:5678",
        **extra,
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.auth import router as auth_router
    app.include_router(auth_router)
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
            "VALUES ('admin@t','x','Admin','admin') RETURNING id")
    token = auth.generate_access_token(admin_id, "admin@t", "admin")
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "admin_id": admin_id, "auth_svc": auth,
                   "auth": {"Authorization": f"Bearer {token}"}}
        finally:
            await close_pool()


async def _new_invite(env, role="member") -> dict:
    r = await env["client"].post("/api/auth/invite", json={"role": role}, headers=env["auth"])
    assert r.status_code == 200
    return r.json()


# --- R2.5: a registered member lands in the default workspace ---------------
async def test_register_seeds_member_into_default_workspace(env):
    inv = await _new_invite(env)
    r = await env["client"].post("/api/auth/register", json={
        "email": "newbie@t", "password": _STRONG, "display_name": "Newbie",
        "invite_token": inv["token"]})
    assert r.status_code == 200, r.text
    uid = r.json()["id"]
    async with env["pool"].acquire() as conn:
        ws = await conn.fetchval(
            "SELECT count(*) FROM public.bh_workspace_users WHERE user_id=$1 AND role='member'", uid)
    assert ws >= 1


# --- R2.2: revoke prevents register -----------------------------------------
async def test_revoke_prevents_register(env):
    inv = await _new_invite(env)
    # Find the invite id.
    async with env["pool"].acquire() as conn:
        invite_id = await conn.fetchval(
            "SELECT id FROM public.bh_invite_links WHERE token=$1", inv["token"])
    rv = await env["client"].post(f"/api/auth/invites/{invite_id}/revoke", headers=env["auth"])
    assert rv.status_code == 200
    # Registration with the revoked token now fails.
    r = await env["client"].post("/api/auth/register", json={
        "email": "blocked@t", "password": _STRONG, "display_name": "Blocked",
        "invite_token": inv["token"]})
    assert r.status_code == 400
    # Revoking a non-existent / already-revoked invite is a 404.
    assert (await env["client"].post(f"/api/auth/invites/{invite_id}/revoke",
                                     headers=env["auth"])).status_code == 404


async def test_revoke_requires_users_manage(env):
    inv = await _new_invite(env)
    async with env["pool"].acquire() as conn:
        invite_id = await conn.fetchval(
            "SELECT id FROM public.bh_invite_links WHERE token=$1", inv["token"])
        member_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t','x','M','member') RETURNING id")
    member_tok = env["auth_svc"].generate_access_token(member_id, "m@t", "member")
    r = await env["client"].post(f"/api/auth/invites/{invite_id}/revoke",
                                 headers={"Authorization": f"Bearer {member_tok}"})
    assert r.status_code == 403


# --- R2.4: admin reset-link rotates a password ------------------------------
async def test_admin_reset_link_rotates_password(env):
    # Seed a member with a known password via the service.
    target = await env["auth_svc"].create_user("u@t", "OldP@ssword-123", "U", "member")
    link = await env["client"].post(f"/api/auth/users/{target['id']}/reset-link", headers=env["auth"])
    assert link.status_code == 200
    token = link.json()["reset_url"].split("token=")[1]
    new_pw = "Brand-New-P@ss-77"
    r = await env["client"].post("/api/auth/reset-password",
                                 json={"token": token, "new_password": new_pw})
    assert r.status_code == 200, r.text
    # Old password no longer authenticates; new one does.
    assert await env["auth_svc"].authenticate("u@t", "OldP@ssword-123") is None
    assert await env["auth_svc"].authenticate("u@t", new_pw) is not None


# --- R2.3: password policy on register AND reset ----------------------------
async def test_register_rejects_short_password(env):
    inv = await _new_invite(env)
    r = await env["client"].post("/api/auth/register", json={
        "email": "short@t", "password": "Sh0rt-9", "display_name": "S",  # < 10
        "invite_token": inv["token"]})
    assert r.status_code == 422  # pydantic min_length=10


async def test_register_rejects_common_password(env):
    inv = await _new_invite(env)
    r = await env["client"].post("/api/auth/register", json={
        "email": "common@t", "password": "password12", "display_name": "C",  # 10 but common
        "invite_token": inv["token"]})
    assert r.status_code == 400


async def test_reset_rejects_common_password(env):
    target = await env["auth_svc"].create_user("r@t", "OldP@ssword-123", "R", "member")
    token = (await env["client"].post(
        f"/api/auth/users/{target['id']}/reset-link", headers=env["auth"])).json()["reset_url"].split("token=")[1]
    r = await env["client"].post("/api/auth/reset-password",
                                 json={"token": token, "new_password": "password12"})
    assert r.status_code == 400


# --- R2.6: first-admin display name from env / email local-part -------------
async def test_first_admin_display_name_from_env(fresh_db, db_settings):
    config = _config(fresh_db, db_settings, ADMIN_EMAIL="owner@house.local",
                     ADMIN_PASSWORD="Sup3r-Strong-PW", ADMIN_DISPLAY_NAME="Dana")
    pool = await init_pool(config)
    await run_migrations(pool)
    try:
        await AuthService(pool, config).ensure_admin_exists()
        async with pool.acquire() as conn:
            name = await conn.fetchval(
                "SELECT display_name FROM public.bh_users WHERE email='owner@house.local'")
        assert name == "Dana"
    finally:
        await close_pool()


async def test_first_admin_display_name_falls_back_to_local_part(fresh_db, db_settings):
    config = _config(fresh_db, db_settings, ADMIN_EMAIL="owner@house.local",
                     ADMIN_PASSWORD="Sup3r-Strong-PW", ADMIN_DISPLAY_NAME="")
    pool = await init_pool(config)
    await run_migrations(pool)
    try:
        await AuthService(pool, config).ensure_admin_exists()
        async with pool.acquire() as conn:
            name = await conn.fetchval(
                "SELECT display_name FROM public.bh_users WHERE email='owner@house.local'")
        assert name == "owner"  # no hardcoded "Michael"
    finally:
        await close_pool()
