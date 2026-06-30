"""Lists v2 — Task 4: the REST router (ID routes, stores, field integrity, shims)."""

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
        JWT_SECRET="test-secret-router-v2", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    auth = AuthService(pool, config)
    async with pool.acquire() as conn:
        mi = await conn.fetchval(
            "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
            "VALUES ('mi@t','x','Michael','admin') RETURNING id")
    headers = {"Authorization": "Bearer " + auth.generate_access_token(mi, "mi@t", "admin")}
    app = FastAPI()
    app.state.config = config
    from backend.routers.lists import router
    app.include_router(router)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "h": headers, "pool": pool, "mi": mi}
        finally:
            await close_pool()


async def _grocery_type(pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval("SELECT id FROM public.bh_list_types WHERE name='grocery'")


async def test_create_get_add_and_schema(env):
    c, h = env["client"], env["h"]
    gt = await _grocery_type(env["pool"])
    r = await c.post("/api/lists", json={"name": "Groceries", "list_type_id": gt}, headers=h)
    assert r.status_code == 200
    lid = r.json()["id"]
    # Add a store so the multi-select store field validates.
    await c.post("/api/lists/stores", json={"name": "Meijer"}, headers=h)
    r = await c.post(f"/api/lists/{lid}/items",
                     json={"items": [{"text": "milk", "category": "Dairy", "attributes": {"store": ["Meijer"]}}]},
                     headers=h)
    assert r.status_code == 200
    body = r.json()
    assert any(f["key"] == "store" for f in body["schema"])      # schema returned
    assert body["items"][0]["text"] == "milk"
    assert body["items"][0]["category"] == "Dairy"
    # Bad store option → 422.
    r = await c.post(f"/api/lists/{lid}/items",
                     json={"items": [{"text": "x", "attributes": {"store": ["Costco"]}}]}, headers=h)
    assert r.status_code == 422


async def test_duplicate_create_conflicts_and_delete_needs_confirm(env):
    c, h = env["client"], env["h"]
    r = await c.post("/api/lists", json={"name": "Todo"}, headers=h)
    lid = r.json()["id"]
    assert (await c.post("/api/lists", json={"name": "todo"}, headers=h)).status_code == 409
    assert (await c.delete(f"/api/lists/{lid}", headers=h)).status_code == 400      # no confirm
    assert (await c.delete(f"/api/lists/{lid}?confirm=true", headers=h)).status_code == 200


async def test_field_integrity_core_hidden_per_list_only(env):
    c, h = env["client"], env["h"]
    gt = await _grocery_type(env["pool"])
    l1 = (await c.post("/api/lists", json={"name": "L1", "list_type_id": gt}, headers=h)).json()["id"]
    l2 = (await c.post("/api/lists", json={"name": "L2", "list_type_id": gt}, headers=h)).json()["id"]
    # Soft-remove the core 'notes' field on L1 only.
    r = await c.patch(f"/api/lists/{l1}/fields/notes", json={"is_active": False}, headers=h)
    assert r.status_code == 200
    f1 = {f["key"] for f in (await c.get(f"/api/lists/{l1}/fields", headers=h)).json()["fields"]}
    f2 = {f["key"] for f in (await c.get(f"/api/lists/{l2}/fields", headers=h)).json()["fields"]}
    assert "notes" not in f1 and "notes" in f2          # per-list only; sibling untouched
    # The core def row itself is untouched (still exactly one, still active).
    async with env["pool"].acquire() as conn:
        core = await conn.fetchrow(
            "SELECT count(*) n, bool_and(is_active) act FROM public.bh_list_field_defs "
            "WHERE scope='core' AND key='notes'")
        assert core["n"] == 1 and core["act"] is True


async def test_custom_column_lifecycle(env):
    c, h = env["client"], env["h"]
    lid = (await c.post("/api/lists", json={"name": "Trip"}, headers=h)).json()["id"]
    # Add a number column, set a value, reject a bad value, then remove it.
    assert (await c.post(f"/api/lists/{lid}/fields",
            json={"key": "budget", "label": "Budget", "col_type": "number"}, headers=h)).status_code == 200
    add = await c.post(f"/api/lists/{lid}/items",
                       json={"items": [{"text": "tent", "attributes": {"budget": 50}}]}, headers=h)
    assert add.status_code == 200
    item_id = add.json()["items"][0]["id"]
    bad = await c.patch(f"/api/lists/items/{item_id}", json={"budget": "lots"}, headers=h)
    assert bad.status_code == 422
    # Soft-remove keeps the stored value in attributes.
    await c.patch(f"/api/lists/{lid}/fields/budget", json={"is_active": False}, headers=h)
    async with env["pool"].acquire() as conn:
        attrs = await conn.fetchval("SELECT attributes FROM public.bh_list_items WHERE id=$1", item_id)
    assert attrs.get("budget") == 50


async def test_store_add_appears_in_field_options(env):
    c, h = env["client"], env["h"]
    gt = await _grocery_type(env["pool"])
    lid = (await c.post("/api/lists", json={"name": "G", "list_type_id": gt}, headers=h)).json()["id"]
    await c.post("/api/lists/stores", json={"name": "Kroger"}, headers=h)
    fields = (await c.get(f"/api/lists/{lid}/fields", headers=h)).json()["fields"]
    store = next(f for f in fields if f["key"] == "store")
    assert any(o["value"] == "Kroger" for o in store["options"])


async def test_name_shim_still_works(env):
    c, h = env["client"], env["h"]
    # Old name-addressed POST creates-on-add and GET reads it back.
    await c.post("/api/lists/shopping/items", json={"items": ["bananas"]}, headers=h)
    r = await c.get("/api/lists/shopping", headers=h)
    assert r.status_code == 200
    assert any(i["text"] == "bananas" for i in r.json()["items"])
