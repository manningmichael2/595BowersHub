"""Lists v2 — migration 0054 (schema spine, seeds, backfill, dedupe, safety FKs).

These cover Task 1 of the lists-v2 spec: the migration applies on a fresh DB,
seeds the typed-list config, widens kb_chunks for list embeddings, elects a
default list, keeps the assignee FK non-destructive, and the R2.2 dedupe merges
colliding shared lists without losing items.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations

pytestmark = pytest.mark.asyncio

_MIGRATION_0054 = (
    Path(__file__).resolve().parents[1] / "migrations" / "0054_lists_v2.sql"
).read_text()


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-lists-v2", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def pool(fresh_db, db_settings) -> AsyncIterator:
    p = await init_pool(_config(fresh_db, db_settings))
    await run_migrations(p)
    try:
        yield p
    finally:
        await close_pool()


async def _mk_user(conn, email: str, name: str, role: str = "member") -> int:
    return await conn.fetchval(
        "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
        "VALUES ($1,'x',$2,$3) RETURNING id", email, name, role)


async def test_types_and_fields_seeded(pool):
    async with pool.acquire() as conn:
        types = await conn.fetchval("SELECT count(*) FROM public.bh_list_types WHERE is_seed")
        assert types == 6
        # Core fields exist as columns.
        core = await conn.fetchval(
            "SELECT count(*) FROM public.bh_list_field_defs WHERE scope='core' AND storage='column'")
        assert core >= 7
        # Grocery has a multi-select store field sourced from bh_stores.
        store = await conn.fetchrow(
            "SELECT col_type, options_source FROM public.bh_list_field_defs d "
            "JOIN public.bh_list_types t ON t.id=d.list_type_id "
            "WHERE t.name='grocery' AND d.key='store' AND d.scope='type'")
        assert store["col_type"] == "multi_select" and store["options_source"] == "stores"
        # Grocery relabels the category column to "Department" and groups by it.
        dept = await conn.fetchval(
            "SELECT d.label FROM public.bh_list_field_defs d JOIN public.bh_list_types t ON t.id=d.list_type_id "
            "WHERE t.name='grocery' AND d.key='category' AND d.scope='type'")
        assert dept == "Department"
        grp = await conn.fetchval("SELECT group_by FROM public.bh_list_types WHERE name='grocery'")
        assert grp == "category"
        # Grocery departments are an ordered set.
        cats = await conn.fetchval("SELECT jsonb_array_length(category_set) FROM public.bh_list_types WHERE name='grocery'")
        assert cats >= 10


async def test_config_rows_and_default_election(pool):
    async with pool.acquire() as conn:
        routing = await conn.fetchval(
            "SELECT value_json FROM public.bh_platform_settings WHERE key='lists.routing'")
        assert {"match_threshold", "create_threshold", "ambiguity_margin"} <= set(routing.keys())
        # No pre-existing lists on a fresh DB → default elects to null (router lazily creates).
        default = await conn.fetchval(
            "SELECT value_json FROM public.bh_platform_settings WHERE key='lists.default_list_id'")
        assert default is None  # jsonb 'null' decodes to Python None


async def test_kb_chunks_allows_list_source(pool):
    async with pool.acquire() as conn:
        # Would raise check_violation before the Part 6 widen.
        await conn.execute(
            "INSERT INTO public.kb_chunks (source_type, source_id, content, content_hash) "
            "VALUES ('list', 1, 'groceries', 'h1')")
        got = await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE source_type='list'")
        assert got == 1


async def test_member_deletion_nulls_assignee_keeps_item(pool):
    # List owned by Michael, item ASSIGNED to Manon. Deleting Manon must null the
    # assignment (ON DELETE SET NULL) but never delete the item. (Owner is distinct
    # from assignee on purpose: bh_lists.user_id is ON DELETE CASCADE, so deleting a
    # list's *owner* still cascades that list — a pre-existing baseline behavior.)
    async with pool.acquire() as conn:
        michael = await _mk_user(conn, "mi@t", "Michael", "admin")
        manon = await _mk_user(conn, "ma@t", "Manon")
        simple = await conn.fetchval("SELECT id FROM public.bh_list_types WHERE name='simple'")
        lst = await conn.fetchval(
            "INSERT INTO public.bh_lists (name, user_id, list_type_id, is_shared) "
            "VALUES ('chores',$1,$2,true) RETURNING id", michael, simple)
        item = await conn.fetchval(
            "INSERT INTO public.bh_list_items (list_id, text, assignee_user_id) "
            "VALUES ($1,'take out trash',$2) RETURNING id", lst, manon)
        await conn.execute("DELETE FROM public.bh_users WHERE id=$1", manon)
        row = await conn.fetchrow(
            "SELECT assignee_user_id FROM public.bh_list_items WHERE id=$1", item)
        assert row is not None, "deleting a member must NOT delete their assigned item"
        assert row["assignee_user_id"] is None


async def test_migration_idempotent_reapply(pool):
    async with pool.acquire() as conn:
        await conn.execute(_MIGRATION_0054)  # re-run the whole file
        # Seeds are guarded → still exactly 6 types, no duplicate core fields.
        assert await conn.fetchval("SELECT count(*) FROM public.bh_list_types WHERE is_seed") == 6
        assert await conn.fetchval(
            "SELECT count(*) FROM public.bh_list_field_defs WHERE scope='core' AND key='text'") == 1


async def test_dedupe_merges_duplicate_shared_lists(pool):
    """Seed colliding shared lists (with the index removed), re-run 0054, assert merge."""
    async with pool.acquire() as conn:
        mi = await _mk_user(conn, "mi@t", "Michael", "admin")
        ma = await _mk_user(conn, "ma@t", "Manon")
        grocery = await conn.fetchval("SELECT id FROM public.bh_list_types WHERE name='grocery'")
        # Drop the shared-name index so we can stage a pre-dedupe duplicate.
        await conn.execute("DROP INDEX IF EXISTS public.uq_lists_shared_name")
        keep = await conn.fetchval(
            "INSERT INTO public.bh_lists (name,user_id,list_type_id,is_shared) "
            "VALUES ('Groceries',$1,$2,true) RETURNING id", mi, grocery)
        await conn.execute("INSERT INTO public.bh_list_items (list_id,text) VALUES ($1,'milk')", keep)
        dup = await conn.fetchval(
            "INSERT INTO public.bh_lists (name,user_id,list_type_id,is_shared) "
            "VALUES ('groceries',$1,$2,true) RETURNING id", ma, grocery)
        await conn.execute("INSERT INTO public.bh_list_items (list_id,text) VALUES ($1,'eggs')", dup)

        await conn.execute(_MIGRATION_0054)  # re-run → Part 7 merges the dup

        # Survivor (lowest id) holds both items; loser archived; nothing lost.
        survivor_items = await conn.fetchval(
            "SELECT count(*) FROM public.bh_list_items WHERE list_id=$1", keep)
        assert survivor_items == 2
        assert await conn.fetchval("SELECT is_archived FROM public.bh_lists WHERE id=$1", dup) is True
        merge = await conn.fetchrow(
            "SELECT survivor_id, item_count FROM public.bh_list_merges WHERE merged_id=$1", dup)
        assert merge["survivor_id"] == keep and merge["item_count"] == 1
        # Index is back and now enforces household-wide shared uniqueness.
        assert await conn.fetchval(
            "SELECT count(*) FROM pg_indexes WHERE indexname='uq_lists_shared_name'") == 1
        total_items = await conn.fetchval("SELECT count(*) FROM public.bh_list_items")
        assert total_items == 2  # zero item loss
