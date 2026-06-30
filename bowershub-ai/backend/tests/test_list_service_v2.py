"""Lists v2 — Task 3: ID-addressed service (resolve/create split, ordering, lifecycle)."""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, get_pool, init_pool, run_migrations
from backend.services import lists as svc
from backend.services.lists import ListError
from backend.services.list_schema import ListSchemaError

pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-svc-v2", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def setup(fresh_db, db_settings) -> AsyncIterator[dict]:
    pool = await init_pool(_config(fresh_db, db_settings))
    await run_migrations(pool)
    async with pool.acquire() as conn:
        mi = await conn.fetchval(
            "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
            "VALUES ('mi@t','x','Michael','admin') RETURNING id")
        ma = await conn.fetchval(
            "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
            "VALUES ('ma@t','x','Manon','member') RETURNING id")
    try:
        yield {"pool": pool, "mi": mi, "ma": ma}
    finally:
        await close_pool()


async def test_resolve_only_never_creates(setup):
    pool = setup["pool"]
    async with pool.acquire() as conn:
        assert await svc.resolve_only(conn, "ghost", setup["mi"]) is None
        # And nothing was inserted.
        assert await conn.fetchval("SELECT count(*) FROM public.bh_lists") == 0


async def test_create_list_and_duplicate_guard(setup):
    pool = setup["pool"]
    async with pool.acquire() as conn:
        lid = await svc.create_list(conn, "Groceries", setup["mi"])
        # Defaults to the 'simple' type.
        tname = await conn.fetchval(
            "SELECT t.name FROM public.bh_lists l JOIN public.bh_list_types t ON t.id=l.list_type_id "
            "WHERE l.id=$1", lid)
        assert tname == "simple"
        # Second shared list with the same (case-insensitive) name is rejected.
        with pytest.raises(ListError):
            await svc.create_list(conn, "groceries", setup["ma"])


async def test_add_items_by_id_validates_and_dedups(setup):
    pool = setup["pool"]
    async with pool.acquire() as conn:
        gtype = await conn.fetchval("SELECT id FROM public.bh_list_types WHERE name='grocery'")
        lid = await svc.create_list(conn, "Groceries", setup["mi"], list_type_id=gtype)
        await conn.execute("INSERT INTO public.bh_stores (name) VALUES ('Meijer')")
    out = await svc.add_items_by_id(
        lid, [{"text": "milk", "category": "Dairy", "attributes": None,
               "store": ["Meijer"]}, "eggs", "milk"], user_id=setup["mi"])
    # 'milk' added once (dup skipped), 'eggs' added → 2 added.
    assert out["count"] == 2
    got = await svc.get_items_by_id(lid, user_id=setup["mi"])
    texts = {i["text"] for i in got["items"]}
    assert texts == {"milk", "eggs"}
    milk = next(i for i in got["items"] if i["text"] == "milk")
    assert milk["category"] == "Dairy"
    # Bad store value is rejected by schema validation.
    with pytest.raises(ListSchemaError):
        await svc.add_items_by_id(lid, [{"text": "bread", "store": ["Costco"]}], user_id=setup["mi"])


async def test_add_items_by_id_no_autocreate(setup):
    # A bogus list id is not accessible → ListError, and no list is created.
    with pytest.raises(ListError):
        await svc.add_items_by_id(99999, ["milk"], user_id=setup["mi"])
    async with setup["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM public.bh_lists") == 0


async def test_reorder_and_move(setup):
    pool = setup["pool"]
    async with pool.acquire() as conn:
        lid = await svc.create_list(conn, "Todo", setup["mi"])
    await svc.add_items_by_id(lid, ["a", "b", "c"], user_id=setup["mi"])
    items = (await svc.get_items_by_id(lid, setup["mi"]))["items"]
    ids = {i["text"]: i["id"] for i in items}
    # Reverse via full reorder.
    await svc.reorder(lid, [ids["c"], ids["b"], ids["a"]], setup["mi"])
    order = [i["text"] for i in (await svc.get_items_by_id(lid, setup["mi"]))["items"]]
    assert order == ["c", "b", "a"]
    # Move 'a' between 'c' and 'b'.
    await svc.move_item(ids["a"], before_id=ids["c"], after_id=ids["b"], user_id=setup["mi"])
    order = [i["text"] for i in (await svc.get_items_by_id(lid, setup["mi"]))["items"]]
    assert order == ["c", "a", "b"]


async def test_move_rebalances_on_underflow(setup):
    pool = setup["pool"]
    async with pool.acquire() as conn:
        lid = await svc.create_list(conn, "Todo", setup["mi"])
    await svc.add_items_by_id(lid, ["x", "y", "z"], user_id=setup["mi"])
    items = (await svc.get_items_by_id(lid, setup["mi"]))["items"]
    ids = {i["text"]: i["id"] for i in items}
    # Force y and z to share a sort_order (gap 0 < epsilon).
    async with pool.acquire() as conn:
        so = await conn.fetchval("SELECT sort_order FROM public.bh_list_items WHERE id=$1", ids["y"])
        await conn.execute("UPDATE public.bh_list_items SET sort_order=$2 WHERE id=$1", ids["z"], so)
        moved = await svc.move_item(ids["x"], before_id=ids["y"], after_id=ids["z"], user_id=setup["mi"])
        assert moved is True
        # All sort_orders distinct after the rebalance.
        sos = await conn.fetch("SELECT sort_order FROM public.bh_list_items WHERE list_id=$1", lid)
        vals = [r["sort_order"] for r in sos]
        assert len(set(vals)) == len(vals)


async def test_lifecycle_rename_archive_delete(setup):
    pool = setup["pool"]
    async with pool.acquire() as conn:
        lid = await svc.create_list(conn, "Camping", setup["mi"])
    assert await svc.rename_list(lid, "Camping Trip", setup["mi"]) is True
    assert await svc.set_archived(lid, True, setup["mi"]) is True
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT name, is_archived FROM public.bh_lists WHERE id=$1", lid)
        assert row["name"] == "Camping Trip" and row["is_archived"] is True
    assert await svc.delete_list(lid, setup["mi"]) is True
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT count(*) FROM public.bh_lists WHERE id=$1", lid) == 0
