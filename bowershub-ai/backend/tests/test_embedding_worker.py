"""
EmbeddingWorker — real-DB integration (R2.2–R2.7, R3.4).

Exercises the actual reconcile + halfvec write path against the pgvector test DB
with a network-free fake client (replaces the prior mock-only coverage). Covers:
  new message/entity embedded; noise roles never chunked; restart resumes from a
  transient failure; version bump re-embeds; entity edit replaces the vector;
  delete + soft-delete (is_active=false) reaps the chunk; backfill idempotency;
  dead-letter after max attempts.
"""

from __future__ import annotations

import json

import pytest

from backend.database import close_pool
from backend.services.embedding_worker import EmbeddingWorker
from backend.tests.semantic_helpers import (
    FakeEmbeddingsClient,
    add_entity,
    add_message,
    apply_migrations,
    seed_user_and_conversation,
)

pytestmark = pytest.mark.asyncio


async def _counts(conn):
    return {
        "total": await conn.fetchval("SELECT count(*) FROM public.kb_chunks"),
        "done": await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE embed_state='done'"),
        "pending": await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE embed_state='pending'"),
        "dead": await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE embed_state='dead'"),
        "embedded": await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE embedding IS NOT NULL"),
    }


async def test_new_message_and_entity_embedded_noise_skipped(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            await add_message(conn, conv, "user", "what is the capital of france")
            await add_message(conn, conv, "assistant", "the capital of france is paris")
            await add_message(conn, conv, "system", "you are helpful")     # noise
            await add_message(conn, conv, "tool_call", "search(paris)")    # noise
            await add_message(conn, conv, "tool_result", "{...}")          # noise
            await add_entity(conn, "Paris", "Capital city of France")

        await EmbeddingWorker(FakeEmbeddingsClient(), pool).run_tick()

        async with pool.acquire() as conn:
            c = await _counts(conn)
            assert c["total"] == 3 and c["done"] == 3 and c["embedded"] == 3
            noise = await conn.fetchval(
                """
                SELECT count(*) FROM public.kb_chunks k
                JOIN public.bh_messages m ON m.id = k.source_id AND k.source_type='message'
                WHERE m.role NOT IN ('user','assistant')
                """
            )
            assert noise == 0
    finally:
        await close_pool()


async def test_unchanged_rerun_is_noop(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            await add_message(conn, conv, "user", "stable message")
        client = FakeEmbeddingsClient()
        worker = EmbeddingWorker(client, pool)
        await worker.run_tick()
        await worker.run_tick()   # second tick: nothing dirty
        # only the first tick should have called the embedder
        assert len(client.calls) == 1
    finally:
        await close_pool()


async def test_restart_resumes_from_transient_failure(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            await add_message(conn, conv, "user", "remember my dentist is dr smith")

        client = FakeEmbeddingsClient()
        client.fail = True
        worker = EmbeddingWorker(client, pool, backoff_base_seconds=0)
        await worker.run_tick()
        async with pool.acquire() as conn:
            c = await _counts(conn)
            assert c["pending"] == 1 and c["embedded"] == 0   # written pending, not embedded

        client.fail = False
        await worker.run_tick()   # retry path picks up the pending row
        async with pool.acquire() as conn:
            c = await _counts(conn)
            assert c["done"] == 1 and c["embedded"] == 1 and c["pending"] == 0
    finally:
        await close_pool()


async def test_version_bump_reembeds(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            await add_message(conn, conv, "user", "favorite color is teal")
        worker = EmbeddingWorker(FakeEmbeddingsClient(), pool)
        await worker.run_tick()
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT embedding_version FROM public.kb_chunks") == 1
            await conn.execute(
                "UPDATE public.bh_platform_settings SET value_json=$1 WHERE key='embedding_config'",
                json.dumps({"model": "bge-m3", "dim": 1024, "version": 2, "metric": "cosine"}),
            )
        await worker.run_tick()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT embedding_version, embed_state FROM public.kb_chunks")
            assert row["embedding_version"] == 2 and row["embed_state"] == "done"
    finally:
        await close_pool()


async def test_edit_entity_replaces_vector(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            eid = await add_entity(conn, "Manon", "Likes cats")
        worker = EmbeddingWorker(FakeEmbeddingsClient(), pool)
        await worker.run_tick()
        async with pool.acquire() as conn:
            h1 = await conn.fetchval("SELECT content_hash FROM public.kb_chunks WHERE source_id=$1", eid)
            await conn.execute(
                "UPDATE public.bh_entities SET summary='Likes dogs and hiking', updated_at=now() WHERE id=$1",
                eid,
            )
        await worker.run_tick()
        async with pool.acquire() as conn:
            h2 = await conn.fetchval("SELECT content_hash FROM public.kb_chunks WHERE source_id=$1", eid)
            content = await conn.fetchval("SELECT content FROM public.kb_chunks WHERE source_id=$1", eid)
            n = await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE source_id=$1", eid)
            assert h2 != h1 and "dogs and hiking" in content and n == 1
    finally:
        await close_pool()


async def test_delete_and_soft_delete_reaps(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            eid = await add_entity(conn, "Temp", "to be deleted")
        worker = EmbeddingWorker(FakeEmbeddingsClient(), pool)
        await worker.run_tick()
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE source_id=$1", eid) == 1
            # soft delete (the app's delete path for entities) must reap the chunk
            await conn.execute("UPDATE public.bh_entities SET is_active=false WHERE id=$1", eid)
        await worker.run_tick()
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT count(*) FROM public.kb_chunks WHERE source_id=$1", eid) == 0
    finally:
        await close_pool()


async def test_backfill_idempotent(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            for i in range(10):
                await add_message(conn, conv, "user", f"message number {i}")
            for i in range(5):
                await add_entity(conn, f"Entity{i}", f"summary {i}")
        worker = EmbeddingWorker(FakeEmbeddingsClient(), pool, batch_size=4)
        # several ticks to drain all batches
        for _ in range(6):
            await worker.run_tick()
        async with pool.acquire() as conn:
            c = await _counts(conn)
            assert c["total"] == 15 and c["done"] == 15
        # re-running inserts nothing new
        await worker.run_tick()
        async with pool.acquire() as conn:
            assert (await _counts(conn))["total"] == 15
    finally:
        await close_pool()


async def test_dead_letter_after_max_attempts(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            await add_message(conn, conv, "user", "this will fail to embed")
        client = FakeEmbeddingsClient()
        client.fail = True
        worker = EmbeddingWorker(client, pool, max_attempts=2, backoff_base_seconds=0)
        await worker.run_tick()   # attempts 0 -> 1, pending
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT embed_state FROM public.kb_chunks") == "pending"
        await worker.run_tick()   # attempts 1 -> 2 >= max -> dead
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT embed_state, last_error FROM public.kb_chunks")
            assert row["embed_state"] == "dead" and row["last_error"]
        # dead row with unchanged content is NOT retried, even once embedding recovers
        client.fail = False
        await worker.run_tick()
        assert client.calls == []   # dead+unchanged never reselected
        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT embed_state FROM public.kb_chunks") == "dead"
    finally:
        await close_pool()
