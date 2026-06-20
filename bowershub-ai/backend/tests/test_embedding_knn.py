"""Task 8 — EmbeddingKNN tier (R2.3).

Majority-vote + agreement-fraction confidence; cold-start category-description
fallback; graceful abstain when Ollama is down; the HNSW index applies on
fresh_db; embed_merchants/embed_categories populate vectors.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.categorization.base import TxnContext
from backend.services.categorization.knn import (
    EmbeddingKNN,
    embed_categories,
    embed_merchants,
)
from backend.tests.semantic_helpers import DIM, FakeEmbeddingsClient, apply_migrations


def _unit_vec(hot: int) -> list[float]:
    """A 1024-dim one-hot vector — cosine distance 0 to itself, 1 to other indices."""
    v = [0.0] * DIM
    v[hot] = 1.0
    return v


async def _merchant(conn, key, *, embedding=None, category_prior_id=None):
    await conn.execute(
        "INSERT INTO finance.merchants (merchant_key, display_name, category_prior_id, embedding) "
        "VALUES ($1, $2, $3, $4::public.halfvec)",
        key, key.title(), category_prior_id, embedding)


@pytest.mark.asyncio
async def test_majority_vote_and_agreement_confidence(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            groceries = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Groceries'")
            dining = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
            # Three near neighbors (one-hot dim 5): 2 groceries, 1 dining.
            await _merchant(conn, "A", embedding=_unit_vec(5), category_prior_id=groceries)
            await _merchant(conn, "B", embedding=_unit_vec(5), category_prior_id=groceries)
            await _merchant(conn, "C", embedding=_unit_vec(5), category_prior_id=dining)
            # Two far neighbors (dim 100) — excluded by k=3.
            await _merchant(conn, "D", embedding=_unit_vec(100), category_prior_id=dining)
            await _merchant(conn, "E", embedding=_unit_vec(100), category_prior_id=dining)
            # Query merchant near the cluster, no stored category.
            await _merchant(conn, "QUERY", embedding=_unit_vec(5))

            tier = EmbeddingKNN(conn, FakeEmbeddingsClient(), k=3, min_neighbors=3)
            d = await tier.classify(TxnContext(txn_id="t", description="q", amount=-5.0,
                                               merchant_key="QUERY"))
        assert d.category_id == groceries          # 2 of 3 nearest voted groceries
        assert d.tier == "embedding_knn"
        assert abs(d.confidence - (2 / 3)) < 1e-3  # agreement fraction
        assert d.rationale["source"] == "merchant_knn"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_cold_start_category_fallback(fresh_db, db_settings):
    """Too few categorized neighbors → nearest category-description embedding (B2)."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            groceries = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Groceries'")
            await conn.execute(
                "UPDATE finance.categories SET embedding = $1::public.halfvec WHERE id = $2",
                _unit_vec(7), groceries)
            await _merchant(conn, "QUERY", embedding=_unit_vec(7))  # near the groceries category vec

            tier = EmbeddingKNN(conn, FakeEmbeddingsClient(), k=15, min_neighbors=3)
            d = await tier.classify(TxnContext(txn_id="t", description="q", amount=-5.0,
                                               merchant_key="QUERY"))
        assert d.category_id == groceries
        assert d.rationale["source"] == "category_description"
        assert d.confidence > 0.9  # distance 0 → similarity ~1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_abstains_when_ollama_down(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            client = FakeEmbeddingsClient()
            client.fail = True  # Ollama down
            tier = EmbeddingKNN(conn, client, k=15, min_neighbors=3)
            # No stored embedding for this merchant → must embed → fails → abstain.
            d = await tier.classify(TxnContext(txn_id="t", description="q", amount=-5.0,
                                               merchant_key="NOVEC"))
        assert d.category_id is None
        assert d.rationale.get("reason") == "no_embedding"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_hnsw_index_applies_on_fresh_db(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            idx = await conn.fetchval(
                "SELECT count(*) FROM pg_indexes WHERE schemaname='finance' "
                "AND indexname='merchants_embedding_idx'")
        assert idx == 1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_embed_merchants_and_categories_populate_vectors(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO finance.merchants (merchant_key, display_name) VALUES ('COSTCO','Costco'),('KROGER','Kroger')")

        client = FakeEmbeddingsClient()
        m = await embed_merchants(client, pool, only_missing=True)
        c = await embed_categories(client, pool)
        assert m["embedded"] == 2
        assert c["embedded"] >= 20  # the seeded taxonomy

        async with pool.acquire() as conn:
            with_vec = await conn.fetchval(
                "SELECT count(*) FROM finance.merchants WHERE embedding IS NOT NULL")
            assert with_vec == 2
            # Idempotent: only_missing now finds nothing.
        again = await embed_merchants(client, pool, only_missing=True)
        assert again["embedded"] == 0
    finally:
        await close_pool()
