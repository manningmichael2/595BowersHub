"""Lists v2 — Task 5: embedding worker reconciles + reaps list chunks.

Uses the FakeEmbeddingsClient (no Ollama) — exercises the reconcile/dirty/reap
SQL, not the real model. The cosine-similarity routing itself is validated on a
box with Ollama (calibration, Task 11)."""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.embedding_worker import EmbeddingWorker
from backend.tests.semantic_helpers import FakeEmbeddingsClient, apply_migrations

pytestmark = pytest.mark.asyncio


async def _mk_list(conn, name: str, type_name: str = "grocery", archived: bool = False) -> int:
    uid = await conn.fetchval(
        "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
        "VALUES ($1,'x','U','member') RETURNING id", f"{name}@t")
    tid = await conn.fetchval("SELECT id FROM public.bh_list_types WHERE name=$1", type_name)
    return await conn.fetchval(
        "INSERT INTO public.bh_lists (name,user_id,list_type_id,is_shared,is_archived) "
        "VALUES ($1,$2,$3,true,$4) RETURNING id", name, uid, tid, archived)


async def _list_chunks(conn) -> int:
    return await conn.fetchval(
        "SELECT count(*) FROM public.kb_chunks WHERE source_type='list' AND embedding IS NOT NULL")


async def test_reconcile_embeds_active_list(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            lid = await _mk_list(conn, "Groceries")
        await EmbeddingWorker(FakeEmbeddingsClient(), pool).run_tick()
        async with pool.acquire() as conn:
            assert await _list_chunks(conn) == 1
            row = await conn.fetchrow(
                "SELECT content, embed_state FROM public.kb_chunks "
                "WHERE source_type='list' AND source_id=$1", lid)
            assert row["embed_state"] == "done"
            assert "Groceries" in row["content"] and "Grocery" in row["content"]  # name · type label
    finally:
        await close_pool()


async def test_unchanged_rerun_is_noop_then_rename_reembeds(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        client = FakeEmbeddingsClient()
        worker = EmbeddingWorker(client, pool)
        async with pool.acquire() as conn:
            lid = await _mk_list(conn, "Trip")
        await worker.run_tick()
        first = len(client.calls)
        await worker.run_tick()                      # nothing dirty → no new embed call
        assert len(client.calls) == first
        async with pool.acquire() as conn:
            await conn.execute("UPDATE public.bh_lists SET name='Camping Trip' WHERE id=$1", lid)
        await worker.run_tick()                      # content hash changed → re-embed
        assert len(client.calls) > first
    finally:
        await close_pool()


async def test_archived_list_is_reaped(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        worker = EmbeddingWorker(FakeEmbeddingsClient(), pool)
        async with pool.acquire() as conn:
            lid = await _mk_list(conn, "Groceries")
        await worker.run_tick()
        async with pool.acquire() as conn:
            assert await _list_chunks(conn) == 1
            await conn.execute("UPDATE public.bh_lists SET is_archived=true WHERE id=$1", lid)
        await worker.run_tick()                      # reap pass drops the archived list's chunk
        async with pool.acquire() as conn:
            assert await _list_chunks(conn) == 0
    finally:
        await close_pool()
