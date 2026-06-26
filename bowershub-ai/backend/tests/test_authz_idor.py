"""Task 2 — pre-existing access-hole closures (R1.5).

T-DBBROWSER-1: the DB browser is admin-only end-to-end — a member/viewer GET on
  /api/db/public/bh_users/export-csv is 403 (B1).
T-IDOR-1/2: conversations + their messages are private-per-user — a same-workspace
  non-owner is denied another user's conversation and its messages-by-
  conversation_id. These FAIL against the old "any workspace member" branch and
  pass once _check_conversation_access is owner-or-admin only (D3).
T-IDOR-3: invite creation is admin-only; settings writes are owner-scoped.

Real JWTs exercise the full get_current_user -> live bh_users read path (no
dependency_overrides), so role demotion / ownership are enforced exactly as in
production.
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


pytestmark = pytest.mark.asyncio


def _make_config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-idor-tests",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.conversations import router as conversations_router
    from backend.routers.db_browser import router as db_browser_router
    from backend.routers.auth import router as auth_router
    from backend.routers.settings import router as settings_router
    for r in (conversations_router, db_browser_router, auth_router, settings_router):
        app.include_router(r)
    return app


async def _seed(pool: asyncpg.Pool) -> dict:
    """admin_a, owner (member), other (member), viewer_c — all in workspace 1.
    `owner` owns a conversation (with one message) in workspace 1."""
    async with pool.acquire() as conn:
        ids = {}
        for key, email, role in [
            ("admin", "admin@t.local", "admin"),
            ("owner", "owner@t.local", "member"),
            ("other", "other@t.local", "member"),
            ("viewer", "viewer@t.local", "viewer"),
        ]:
            ids[key] = await conn.fetchval(
                "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
                "VALUES ($1,'x',$2,$3) RETURNING id",
                email, key, role,
            )
            # Same workspace (1 = General, seeded by baseline) for everyone, so the
            # IDOR test proves shared-workspace does NOT grant conversation access.
            await conn.execute(
                "INSERT INTO public.bh_workspace_users (workspace_id, user_id, role) "
                "VALUES (1, $1, $2) ON CONFLICT DO NOTHING",
                ids[key], "member" if role != "viewer" else "viewer",
            )
        conv_id = await conn.fetchval(
            "INSERT INTO public.bh_conversations (workspace_id, user_id, title) "
            "VALUES (1, $1, 'Private') RETURNING id",
            ids["owner"],
        )
        await conn.execute(
            "INSERT INTO public.bh_messages (conversation_id, role, content) "
            "VALUES ($1, 'user', 'secret note')",
            conv_id,
        )
    return {"ids": ids, "conv_id": conv_id}


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _make_config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)  # warm cache (require_admin is rank-only, but future-proof)
    seed = await _seed(pool)

    from backend.services.auth import AuthService
    auth = AuthService(pool, config)
    emails = {"admin": "admin@t.local", "owner": "owner@t.local",
              "other": "other@t.local", "viewer": "viewer@t.local"}
    roles = {"admin": "admin", "owner": "member", "other": "member", "viewer": "viewer"}
    headers = {
        k: {"Authorization": "Bearer " + auth.generate_access_token(
            seed["ids"][k], emails[k], roles[k])}
        for k in emails
    }

    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "headers": headers, "seed": seed, "pool": pool}
        finally:
            await close_pool()


# --- T-DBBROWSER-1 -----------------------------------------------------------
async def test_db_browser_export_csv_is_admin_only(env):
    url = "/api/db/public/bh_users/export-csv"
    assert (await env["client"].get(url, headers=env["headers"]["other"])).status_code == 403
    assert (await env["client"].get(url, headers=env["headers"]["viewer"])).status_code == 403
    # Admin is permitted (200 stream; not a 403).
    assert (await env["client"].get(url, headers=env["headers"]["admin"])).status_code == 200


async def test_db_browser_reads_are_admin_only(env):
    # A representative read endpoint — schemas listing — is also admin-only now.
    r = await env["client"].get("/api/db/schemas", headers=env["headers"]["other"])
    assert r.status_code == 403


# --- T-IDOR-1: conversation -------------------------------------------------
async def test_conversation_private_per_user(env):
    cid = env["seed"]["conv_id"]
    url = f"/api/conversations/{cid}"
    # Same-workspace non-owner + viewer are denied (the old workspace-member
    # branch would have returned 200 here — this asserts it's gone).
    assert (await env["client"].get(url, headers=env["headers"]["other"])).status_code == 403
    assert (await env["client"].get(url, headers=env["headers"]["viewer"])).status_code == 403
    # Owner + admin allowed.
    assert (await env["client"].get(url, headers=env["headers"]["owner"])).status_code == 200
    assert (await env["client"].get(url, headers=env["headers"]["admin"])).status_code == 200


# --- T-IDOR-2: messages-by-conversation_id ----------------------------------
async def test_messages_private_per_user(env):
    cid = env["seed"]["conv_id"]
    url = f"/api/conversations/{cid}/messages"
    assert (await env["client"].get(url, headers=env["headers"]["other"])).status_code == 403
    owner_resp = await env["client"].get(url, headers=env["headers"]["owner"])
    assert owner_resp.status_code == 200
    assert any(m["content"] == "secret note" for m in owner_resp.json())


async def test_share_endpoint_disabled(env):
    cid = env["seed"]["conv_id"]
    other_id = env["seed"]["ids"]["other"]
    # Owner can reach it but it's disabled (410); it never grants cross-user access.
    r = await env["client"].post(
        f"/api/conversations/{cid}/share/{other_id}", headers=env["headers"]["owner"])
    assert r.status_code == 410
    # A non-owner can't even probe it (403 from the ownership check, not 410).
    r2 = await env["client"].post(
        f"/api/conversations/{cid}/share/{other_id}", headers=env["headers"]["other"])
    assert r2.status_code == 403


# --- T-IDOR-3: invites admin-only; settings owner-scoped --------------------
async def test_invite_creation_is_admin_only(env):
    body = {"role": "member"}
    assert (await env["client"].post("/api/auth/invite", json=body,
                                     headers=env["headers"]["other"])).status_code == 403
    assert (await env["client"].post("/api/auth/invite", json=body,
                                     headers=env["headers"]["viewer"])).status_code == 403
    admin_resp = await env["client"].post("/api/auth/invite", json=body,
                                          headers=env["headers"]["admin"])
    assert admin_resp.status_code == 200


async def test_settings_write_is_owner_scoped(env):
    # `other` patches their own settings; `owner`'s row must be untouched (a
    # settings write can only affect the authenticated user — no user_id param).
    r = await env["client"].patch("/api/settings", json={"text_size": "large"},
                                  headers=env["headers"]["other"])
    assert r.status_code == 200
    async with env["pool"].acquire() as conn:
        owner_settings = await conn.fetchval(
            "SELECT settings_json FROM public.bh_users WHERE id = $1",
            env["seed"]["ids"]["owner"],
        )
    # owner never wrote settings -> still NULL/empty; `other`'s write didn't leak.
    assert not owner_settings or "text_size" not in owner_settings
