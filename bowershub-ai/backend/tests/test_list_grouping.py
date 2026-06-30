"""Lists v2 — Task 7: grouping / sorting / filtering + grocery auto-categorize."""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import lists as svc
from backend.services import list_grouping, list_config

pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-group", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    pool = await init_pool(_config(fresh_db, db_settings))
    await run_migrations(pool)
    async with pool.acquire() as conn:
        uid = await conn.fetchval(
            "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
            "VALUES ('mi@t','x','Michael','admin') RETURNING id")
        gtype = await conn.fetchval("SELECT id FROM public.bh_list_types WHERE name='grocery'")
        lid = await conn.fetchval(
            "INSERT INTO public.bh_lists (name,user_id,list_type_id,is_shared) "
            "VALUES ('Groceries',$1,$2,true) RETURNING id", uid, gtype)
    try:
        yield {"pool": pool, "uid": uid, "lid": lid, "gtype": gtype}
    finally:
        await close_pool()


async def test_autocategorize_on_add(env):
    # milk/bread get departments from the seed alias table; unknown stays uncategorized.
    await svc.add_items_by_id(env["lid"], ["milk", "bread", "fluxcapacitor"], user_id=env["uid"])
    items = (await svc.get_items_by_id(env["lid"], env["uid"]))["items"]
    cat = {i["text"]: i["category"] for i in items}
    assert cat["milk"] == "Dairy"
    assert cat["bread"] == "Bakery"
    assert cat["fluxcapacitor"] is None       # no alias → uncategorized, still added


async def test_grouped_by_department_in_category_set_order(env):
    await svc.add_items_by_id(env["lid"], ["milk", "banana", "bread"], user_id=env["uid"])
    async with env["pool"].acquire() as conn:
        view = await list_grouping.grouped_view(conn, env["lid"])
    assert view["group_by"] == "category"
    labels = [g["label"] for g in view["groups"]]
    # category_set order: Produce(banana) before Bakery(bread) before Dairy(milk).
    assert labels.index("Produce") < labels.index("Bakery") < labels.index("Dairy")


async def test_store_filter_and_aisle_order(env):
    pool = env["pool"]
    async with pool.acquire() as conn:
        await conn.execute("INSERT INTO public.bh_stores (name) VALUES ('Meijer'),('Kroger')")
        sid = await conn.fetchval("SELECT id FROM public.bh_stores WHERE name='Meijer'")
    # Meijer walks Dairy before Produce (custom layout).
    await list_config.set_store_aisles(sid, ["Dairy", "Produce", "Bakery"])
    # milk tagged Meijer+Kroger; banana tagged Kroger only; bread untagged.
    await svc.add_items_by_id(env["lid"], [
        {"text": "milk", "attributes": {"store": ["Meijer", "Kroger"]}},
        {"text": "banana", "attributes": {"store": ["Kroger"]}},
        {"text": "bread"},
    ], user_id=env["uid"])
    async with pool.acquire() as conn:
        view = await list_grouping.grouped_view(conn, env["lid"], store="Meijer")
        texts = [it["text"] for g in view["groups"] for it in g["items"]]
        # banana (Kroger-only) is filtered out; milk + untagged bread remain.
        assert "banana" not in texts and "milk" in texts and "bread" in texts
        # Meijer aisle order puts Dairy (milk) before Bakery (bread).
        labels = [g["label"] for g in view["groups"]]
        assert labels.index("Dairy") < labels.index("Bakery")


async def test_sort_whitelist_and_custom_field(env):
    from backend.services import list_schema
    async with env["pool"].acquire() as conn:
        schema = await list_schema.resolve_schema(conn, env["lid"])
    # Built-ins resolve; an injection attempt falls back to manual.
    assert list_grouping._sort_expr("name", schema) == "LOWER(text)"
    assert list_grouping._sort_expr("text; DROP TABLE", schema) == "sort_order"
    assert list_grouping._sort_expr("price", schema) == "(attributes->>'price')::numeric"


async def test_filter_checked(env):
    await svc.add_items_by_id(env["lid"], ["milk", "eggs"], user_id=env["uid"])
    items = (await svc.get_items_by_id(env["lid"], env["uid"]))["items"]
    await svc.set_checked(items[0]["id"], True, env["uid"])
    async with env["pool"].acquire() as conn:
        view = await list_grouping.grouped_view(conn, env["lid"], filters={"checked": False})
    texts = [it["text"] for g in view["groups"] for it in g["items"]]
    assert items[0]["text"] not in texts and len(texts) == 1
