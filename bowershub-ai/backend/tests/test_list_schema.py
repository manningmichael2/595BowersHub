"""Lists v2 — Task 2: the schema engine (resolve + validate + partition)."""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import list_schema as ls
from backend.services.list_schema import FieldDef, ListSchemaError

pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-schema", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def pool(fresh_db, db_settings) -> AsyncIterator:
    p = await init_pool(_config(fresh_db, db_settings))
    await run_migrations(p)
    try:
        yield p
    finally:
        await close_pool()


async def _grocery_list(conn) -> int:
    uid = await conn.fetchval(
        "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
        "VALUES ('mi@t','x','Michael','admin') RETURNING id")
    gtype = await conn.fetchval("SELECT id FROM public.bh_list_types WHERE name='grocery'")
    return await conn.fetchval(
        "INSERT INTO public.bh_lists (name,user_id,list_type_id,is_shared) "
        "VALUES ('Groceries',$1,$2,true) RETURNING id", uid, gtype)


# ── DB-backed resolution ──────────────────────────────────────────────────────

async def test_resolution_precedence_type_overrides_core(pool):
    async with pool.acquire() as conn:
        lst = await _grocery_list(conn)
        schema = await ls.resolve_schema(conn, lst)
        by_key = schema.by_key()
        # type-scope override of the core 'category' field wins (relabelled).
        assert by_key["category"].label == "Department"
        # type-only field present.
        assert by_key["store"].col_type == "multi_select"
        # core field still present.
        assert "text" in by_key and "checked" in by_key


async def test_list_scope_override_wins_and_soft_remove_hides(pool):
    async with pool.acquire() as conn:
        lst = await _grocery_list(conn)
        # A per-list override renames 'store' and soft-removes 'price'.
        await conn.execute(
            "INSERT INTO public.bh_list_field_defs (scope,list_id,key,label,col_type,storage,options_source,filterable) "
            "VALUES ('list',$1,'store','Shop','multi_select','attribute','stores',true)", lst)
        await conn.execute(
            "INSERT INTO public.bh_list_field_defs (scope,list_id,key,label,col_type,storage,is_active) "
            "VALUES ('list',$1,'price','Price','number','attribute',false)", lst)
        schema = await ls.resolve_schema(conn, lst)
        by_key = schema.by_key()
        assert by_key["store"].label == "Shop"          # list scope wins over type
        assert "price" not in by_key                      # soft-removed → hidden


async def test_options_resolved_from_stores(pool):
    async with pool.acquire() as conn:
        lst = await _grocery_list(conn)
        await conn.execute("INSERT INTO public.bh_stores (name) VALUES ('Meijer'),('Kroger')")
        schema = await ls.resolve_schema(conn, lst)
        store = schema.field("store")
        assert store.option_values == {"Meijer", "Kroger"}


async def test_partition_routes_by_storage_and_rejects_unknown(pool):
    async with pool.acquire() as conn:
        lst = await _grocery_list(conn)
        await conn.execute("INSERT INTO public.bh_stores (name) VALUES ('Meijer')")
        schema = await ls.resolve_schema(conn, lst)
        cols, attrs = ls.partition_item_values(
            schema, {"text": "milk", "category": "Dairy", "store": ["Meijer"]})
        assert cols == {"text": "milk", "category": "Dairy"}   # core columns
        assert attrs == {"store": ["Meijer"]}                  # JSONB tail
        with pytest.raises(ListSchemaError):
            ls.partition_item_values(schema, {"nope": 1})
        with pytest.raises(ListSchemaError):
            ls.partition_item_values(schema, {"store": ["Costco"]})  # not an option


# ── Pure validation ───────────────────────────────────────────────────────────

def _f(col_type, **kw) -> FieldDef:
    return FieldDef(key="k", label="K", col_type=col_type, storage="attribute", scope="list", **kw)


def test_validate_number():
    ls.validate_value(_f("number"), 3)
    ls.validate_value(_f("number"), "3.5")
    with pytest.raises(ListSchemaError):
        ls.validate_value(_f("number"), "abc")
    with pytest.raises(ListSchemaError):
        ls.validate_value(_f("number"), True)              # bool is not a number
    with pytest.raises(ListSchemaError):
        ls.validate_value(_f("number", validation={"max": 10}), 11)


def test_validate_select():
    f = _f("single_select", options=[{"value": "low"}, {"value": "high"}])
    ls.validate_value(f, "low")
    with pytest.raises(ListSchemaError):
        ls.validate_value(f, "mid")
    m = _f("multi_select", options=[{"value": "a"}, {"value": "b"}])
    ls.validate_value(m, ["a", "b"])
    with pytest.raises(ListSchemaError):
        ls.validate_value(m, ["a", "z"])


def test_validate_date_url_required():
    ls.validate_value(_f("date"), "2026-06-29")
    with pytest.raises(ListSchemaError):
        ls.validate_value(_f("date"), "not-a-date")
    ls.validate_value(_f("url"), "https://example.com")
    with pytest.raises(ListSchemaError):
        ls.validate_value(_f("url"), "ftp://x")
    with pytest.raises(ListSchemaError):
        ls.validate_value(_f("text", required=True), None)
    ls.validate_value(_f("text"), None)                    # optional → ok
