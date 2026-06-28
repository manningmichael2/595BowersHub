"""Per-user workspace membership admin endpoints (household provisioning).

An admin can list every workspace with a user's membership flag, grant a user
access to a shared workspace, and revoke it — all gated by users.manage, so a
member is 403'd. Closes the "no admin flow to grant workspace access" gap.
"""

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
        JWT_SECRET="test-secret-for-admin-workspaces",
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
        admin_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('a@t','x','A','admin') RETURNING id")
        member_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t','x','Manon','member') RETURNING id")
        ws_id = await conn.fetchval(
            "INSERT INTO public.bh_workspaces (name, description, icon) "
            "VALUES ('Finance','shared','💰') RETURNING id")
    headers = {
        "admin": {"Authorization": "Bearer " + auth.generate_access_token(admin_id, "a@t", "admin")},
        "member": {"Authorization": "Bearer " + auth.generate_access_token(member_id, "m@t", "member")},
    }
    app = FastAPI()
    app.state.config = config
    from backend.routers.admin import router as admin_router
    app.include_router(admin_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "member_id": member_id, "ws_id": ws_id, "headers": headers}
        finally:
            await close_pool()


async def test_grant_then_revoke_workspace(env):
    c, headers, uid, ws = env["client"], env["headers"], env["member_id"], env["ws_id"]

    # Initially the member belongs to no workspace.
    r = await c.get(f"/api/admin/users/{uid}/workspaces", headers=headers["admin"])
    assert r.status_code == 200
    finance = next(w for w in r.json() if w["id"] == ws)
    assert finance["member"] is False and finance["role"] is None

    # Grant access.
    r = await c.put(f"/api/admin/users/{uid}/workspaces/{ws}",
                    json={"role": "member"}, headers=headers["admin"])
    assert r.status_code == 200 and r.json()["member"] is True

    r = await c.get(f"/api/admin/users/{uid}/workspaces", headers=headers["admin"])
    finance = next(w for w in r.json() if w["id"] == ws)
    assert finance["member"] is True and finance["role"] == "member"

    # Revoke.
    r = await c.delete(f"/api/admin/users/{uid}/workspaces/{ws}", headers=headers["admin"])
    assert r.status_code == 200 and r.json()["member"] is False
    r = await c.get(f"/api/admin/users/{uid}/workspaces", headers=headers["admin"])
    assert next(w for w in r.json() if w["id"] == ws)["member"] is False


async def test_member_cannot_manage_workspaces(env):
    c, headers, uid, ws = env["client"], env["headers"], env["member_id"], env["ws_id"]
    # users.manage is admin-gated → a member is denied on all three routes.
    assert (await c.get(f"/api/admin/users/{uid}/workspaces",
                        headers=headers["member"])).status_code == 403
    assert (await c.put(f"/api/admin/users/{uid}/workspaces/{ws}",
                        json={"role": "member"}, headers=headers["member"])).status_code == 403
    assert (await c.delete(f"/api/admin/users/{uid}/workspaces/{ws}",
                           headers=headers["member"])).status_code == 403


async def test_invalid_role_rejected(env):
    c, headers, uid, ws = env["client"], env["headers"], env["member_id"], env["ws_id"]
    r = await c.put(f"/api/admin/users/{uid}/workspaces/{ws}",
                    json={"role": "superuser"}, headers=headers["admin"])
    assert r.status_code == 400


async def test_unknown_user_or_workspace_404(env):
    c, headers, ws = env["client"], env["headers"], env["ws_id"]
    assert (await c.get("/api/admin/users/99999/workspaces",
                        headers=headers["admin"])).status_code == 404
    assert (await c.put(f"/api/admin/users/99999/workspaces/{ws}",
                        json={"role": "member"}, headers=headers["admin"])).status_code == 404
