"""
HybridRetriever — real-DB integration (R3.1, R3.2, R3.3, R3.4).

Against the pgvector test DB with a deterministic fake embedder:
  - vector ANN + RRF returns the nearest-neighbour message (pinned vectors);
  - message results NEVER cross workspace boundaries (R3.3 security);
  - FTS-only degrade returns results when embedding fails, no error (R3.3);
  - entity retrieval excludes is_active=false rows (defense-in-depth, R3.3).
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.embedding_worker import EmbeddingWorker
from backend.services.hybrid_retrieval import HybridRetriever
from backend.tests.semantic_helpers import (
    DIM,
    FakeEmbeddingsClient,
    add_entity,
    add_message,
    apply_migrations,
    seed_user_and_conversation,
)

pytestmark = pytest.mark.asyncio


async def _new_workspace(conn, name: str) -> int:
    return await conn.fetchval(
        "INSERT INTO public.bh_workspaces (name, description) VALUES ($1,$1) RETURNING id", name
    )


async def _conversation_in(conn, workspace_id: int, user_id: int) -> int:
    return await conn.fetchval(
        "INSERT INTO public.bh_conversations (workspace_id, user_id, title) VALUES ($1,$2,'t') RETURNING id",
        workspace_id, user_id,
    )


async def test_vector_nearest_neighbour_via_rrf(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        client = FakeEmbeddingsClient()
        # pin: query vector == the "relevant" doc's vector (distance 0 → rank 1)
        relevant = "the eiffel tower is in paris"
        client.vector_for[relevant] = [1.0] + [0.0] * (DIM - 1)
        client.vector_for["QUERY"] = [1.0] + [0.0] * (DIM - 1)
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            await add_message(conn, conv, "assistant", relevant)
            await add_message(conn, conv, "user", "unrelated chatter about lunch")
        await EmbeddingWorker(client, pool).run_tick()

        retr = HybridRetriever(client, pool)
        results = await retr.search_hybrid("QUERY", "message", limit=5, accessible_workspaces=[1])
        assert results, "expected at least one hit"
        assert results[0]["content"] == relevant   # nearest neighbour ranked first
    finally:
        await close_pool()


async def test_message_results_never_cross_workspace(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv1 = await seed_user_and_conversation(conn, workspace_id=1)
            uid = await conn.fetchval("SELECT user_id FROM public.bh_conversations WHERE id=$1", conv1)
            ws2 = await _new_workspace(conn, "Secret WS")
            conv2 = await _conversation_in(conn, ws2, uid)
            await add_message(conn, conv1, "user", "the secret recipe uses saffron")
            await add_message(conn, conv2, "user", "the secret recipe uses saffron")
        await EmbeddingWorker(FakeEmbeddingsClient(), pool).run_tick()

        retr = HybridRetriever(FakeEmbeddingsClient(), pool)
        only1 = await retr.search_hybrid("secret recipe saffron", "message", limit=10, accessible_workspaces=[1])
        assert only1 and all(r["workspace_id"] == 1 for r in only1)   # no leak from ws2

        both = await retr.search_hybrid("secret recipe saffron", "message", limit=10,
                                        accessible_workspaces=[1, ws2])
        assert {r["workspace_id"] for r in both} == {1, ws2}
    finally:
        await close_pool()


async def test_fts_only_degrade_when_embedding_down(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            conv = await seed_user_and_conversation(conn)
            await add_message(conn, conv, "user", "the quarterly budget review is on friday")
        await EmbeddingWorker(FakeEmbeddingsClient(), pool).run_tick()

        down = FakeEmbeddingsClient()
        down.fail = True                       # query embedding fails → FTS-only
        retr = HybridRetriever(down, pool)
        results = await retr.search_hybrid("budget review", "message", limit=5, accessible_workspaces=[1])
        assert results and "budget review" in results[0]["content"]
    finally:
        await close_pool()


async def test_entity_retrieval_excludes_inactive(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            eid = await add_entity(conn, "Sensitive Project", "codename bluebird launch plan")
        await EmbeddingWorker(FakeEmbeddingsClient(), pool).run_tick()
        # deactivate WITHOUT reaping, to prove the retrieval filter itself excludes it
        async with pool.acquire() as conn:
            await conn.execute("UPDATE public.bh_entities SET is_active=false WHERE id=$1", eid)

        retr = HybridRetriever(FakeEmbeddingsClient(), pool)
        results = await retr.search_hybrid("bluebird launch", "entity", limit=5)
        assert all(r["source_id"] != eid for r in results)   # inactive entity not surfaced
    finally:
        await close_pool()
