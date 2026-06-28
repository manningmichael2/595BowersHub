"""Workspaces are shared household-wide: a member with NO bh_workspace_users
membership rows can still see every workspace and start a conversation in one.
This is the fix for the "signed in as member, no workspace access, can't start a
conversation" symptom. Conversation *content* stays private-per-user (covered in
test_authz_idor)."""

from __future__ import annotations

from typing import AsyncIterator

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
        JWT_SECRET="test-secret-for-shared-workspaces",
        N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    auth = AuthService(pool, config)
    async with pool.acquire() as conn:
        member_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t','x','Manon','member') RETURNING id")
        # A workspace the member is explicitly NOT a member of.
        ws_id = await conn.fetchval(
            "INSERT INTO public.bh_workspaces (name, description, icon) "
            "VALUES ('General','shared','🏠') RETURNING id")
    headers = {"Authorization": "Bearer " + auth.generate_access_token(member_id, "m@t", "member")}
    app = FastAPI()
    app.state.config = config
    from backend.routers.workspaces import router as ws
    from backend.routers.conversations import router as convos
    app.include_router(ws)
    app.include_router(convos)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "ws_id": ws_id, "headers": headers}
        finally:
            await close_pool()


async def test_member_sees_shared_workspace(env):
    r = await env["client"].get("/api/workspaces", headers=env["headers"])
    assert r.status_code == 200
    assert any(w["id"] == env["ws_id"] for w in r.json())


async def test_member_can_start_conversation(env):
    c, headers, ws = env["client"], env["headers"], env["ws_id"]
    r = await c.post("/api/conversations", json={"workspace_id": ws, "title": "hi"}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["workspace_id"] == ws

    # And can list it back.
    r = await c.get(f"/api/conversations?workspace_id={ws}", headers=headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


async def test_unknown_workspace_still_404(env):
    r = await env["client"].post("/api/conversations",
                                 json={"workspace_id": 99999, "title": "x"},
                                 headers=env["headers"])
    assert r.status_code == 404
