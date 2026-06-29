"""Icon library — pick from previously-used app icon sets.

Builds a library by uploading a few icons (active + previous + history), then
exercises list / preview / activate-from-history through the branding store +
router, including admin gating and the public preview.
"""

from __future__ import annotations

import io
import os
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import authz, branding_store
from backend.services.auth import AuthService


pytestmark = pytest.mark.asyncio


def _png(color: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (512, 512), color).save(buf, "PNG")
    return buf.getvalue()


@pytest_asyncio.fixture
async def env(fresh_db, db_settings, tmp_path, monkeypatch) -> AsyncIterator[dict]:
    # branding_store._branding_root() reads FILES_ROOT from the env, not Config.
    monkeypatch.setenv("FILES_ROOT", str(tmp_path))
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=fresh_db, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-branding-lib", N8N_BASE="http://localhost:5678",
        FILES_ROOT=str(tmp_path),
    )
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
    app = FastAPI()
    app.state.config = config
    from backend.routers.branding import router as branding_router
    app.include_router(branding_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "headers": headers}
        finally:
            await close_pool()


async def _seed_three_icons():
    # Uploads build the rotation: active=blue, previous=green, history=[red].
    await branding_store.upload_icon(_png("red"))
    await branding_store.upload_icon(_png("green"))
    await branding_store.upload_icon(_png("blue"))


async def test_library_lists_active_previous_history(env):
    await _seed_three_icons()
    r = await env["client"].get("/api/branding/library", headers=env["headers"]["admin"])
    assert r.status_code == 200
    kinds = {e["kind"] for e in r.json()["entries"]}
    assert kinds == {"active", "previous", "history"}
    active = [e for e in r.json()["entries"] if e["active"]]
    assert len(active) == 1 and active[0]["kind"] == "active"


async def test_library_is_admin_only(env):
    r = await env["client"].get("/api/branding/library", headers=env["headers"]["member"])
    assert r.status_code == 403


async def test_activate_history_entry_makes_it_active(env):
    await _seed_three_icons()
    listing = (await env["client"].get("/api/branding/library", headers=env["headers"]["admin"])).json()
    hist = next(e for e in listing["entries"] if e["kind"] == "history")

    act = await env["client"].post(
        f"/api/branding/library/{hist['id']}/activate", headers=env["headers"]["admin"])
    assert act.status_code == 200 and act.json()["version"]

    # The history entry is consumed (now active); a rollback slot still exists.
    after = (await env["client"].get("/api/branding/library", headers=env["headers"]["admin"])).json()
    assert sum(1 for e in after["entries"] if e["active"]) == 1


async def test_preview_is_public_png(env):
    await _seed_three_icons()
    # No auth header — preview is public (loaded via <img>).
    r = await env["client"].get("/api/branding/library/active/preview")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


async def test_activate_unknown_entry_400(env):
    r = await env["client"].post(
        "/api/branding/library/history/..%2fescape/activate", headers=env["headers"]["admin"])
    assert r.status_code in (400, 404)
