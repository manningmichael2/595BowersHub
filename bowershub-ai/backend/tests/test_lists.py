"""Household-shared lists — the shopping/to-do list feature.

Covers the shared-by-default model (one member adds, the other sees + checks off),
id-based item operations with per-item access control, and the REST surface.
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
from backend.services import lists as svc


pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-lists", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    auth = AuthService(pool, config)
    async with pool.acquire() as conn:
        michael = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('mi@t','x','Michael','admin') RETURNING id")
        manon = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('ma@t','x','Manon','member') RETURNING id")
    headers = {
        "michael": {"Authorization": "Bearer " + auth.generate_access_token(michael, "mi@t", "admin")},
        "manon": {"Authorization": "Bearer " + auth.generate_access_token(manon, "ma@t", "member")},
    }
    app = FastAPI()
    app.state.config = config
    from backend.routers.lists import router as lists_router
    app.include_router(lists_router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "headers": headers,
                   "michael": michael, "manon": manon}
        finally:
            await close_pool()


async def test_shared_list_visible_to_other_member(env):
    # Michael adds via the service; Manon sees the same shared list over the API.
    await svc.add_items("shopping", ["milk", "eggs"], user_id=env["michael"])
    r = await env["client"].get("/api/lists/shopping", headers=env["headers"]["manon"])
    assert r.status_code == 200
    texts = [i["text"] for i in r.json()["items"]]
    assert set(texts) == {"milk", "eggs"}


async def test_member_can_check_and_clear_shared_items(env):
    add = await env["client"].post(
        "/api/lists/shopping/items", json={"items": ["bread", "butter"]},
        headers=env["headers"]["michael"])
    items = {i["text"]: i["id"] for i in add.json()["items"]}

    # Manon checks off bread by id.
    chk = await env["client"].put(
        f"/api/lists/items/{items['bread']}", json={"checked": True},
        headers=env["headers"]["manon"])
    assert chk.status_code == 200 and chk.json()["ok"] is True

    # Michael sees bread checked.
    got = (await env["client"].get("/api/lists/shopping", headers=env["headers"]["michael"])).json()
    by_text = {i["text"]: i for i in got["items"]}
    assert by_text["bread"]["checked"] is True
    assert by_text["butter"]["checked"] is False

    # Clearing removes only the checked item.
    cleared = await env["client"].post(
        "/api/lists/shopping/clear", headers=env["headers"]["manon"])
    remaining = [i["text"] for i in cleared.json()["items"]]
    assert remaining == ["butter"]


async def test_delete_item_by_id(env):
    add = await env["client"].post(
        "/api/lists/shopping/items", json={"items": ["soap"]},
        headers=env["headers"]["michael"])
    iid = add.json()["items"][0]["id"]
    d = await env["client"].delete(f"/api/lists/items/{iid}", headers=env["headers"]["manon"])
    assert d.status_code == 200 and d.json()["ok"] is True
    got = (await env["client"].get("/api/lists/shopping", headers=env["headers"]["michael"])).json()
    assert got["items"] == []


async def test_private_list_not_shared(env):
    # A private (is_shared=false) list stays scoped to its creator.
    async with env["pool"].acquire() as conn:
        lid = await conn.fetchval(
            "INSERT INTO public.bh_lists (name, user_id, is_shared) VALUES ('gifts',$1,false) RETURNING id",
            env["michael"])
        await conn.execute(
            "INSERT INTO public.bh_list_items (list_id, text) VALUES ($1,'watch')", lid)
    # Manon can't see Michael's private list.
    manon_view = (await env["client"].get("/api/lists/gifts", headers=env["headers"]["manon"])).json()
    assert manon_view["items"] == []
    # Michael can.
    mike_view = (await env["client"].get("/api/lists/gifts", headers=env["headers"]["michael"])).json()
    assert [i["text"] for i in mike_view["items"]] == ["watch"]
