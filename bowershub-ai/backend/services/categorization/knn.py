"""EmbeddingKNN — tier 3 (R2.3). Nearest-merchant vote, built on the shipped
bge-m3 / halfvec / HNSW stack, embedding at the MERCHANT level.

Embeds each distinct normalized merchant string once (finance.merchants.embedding)
— far fewer vectors than per-transaction, and "nearest merchants" is exactly the
categorization signal. kNN over neighbors that have a known category → majority
vote, `confidence = agreement fraction`. Below `min_neighbors`, falls back to
nearest category-description embedding (cold-start bootstrap, B2), else abstains
to the LLM. Degrades cleanly when Ollama is down (abstain, like HybridRetriever).

`k` / `min_neighbors` are DB config (finance.categorizer_config → knn), sized
against measured transaction volume.

MEASURED VOLUME (2026-06-20, live `finance` DB): 414 transactions, 372
categorized, ≤ a few hundred distinct merchants. At this single-household scale
the merchant-level vector set is in the hundreds, so the HNSW index is trivially
small and the seeded defaults (k=15, min_neighbors=3) are appropriate — k is well
below the merchant count so neighbors are meaningful, and min_neighbors=3 still
demands genuine local agreement. Task 13 calibrates these against the eval set.
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from ..embeddings import EmbeddingError, EmbeddingsClient
from ..model_catalog import get_embedding_config
from .base import Decision, TxnContext

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[_\s]+")


def _humanize(key_or_name: str) -> str:
    """`Food_Groceries` / `COSTCO WHSE` → a natural string to embed."""
    return _WORD.sub(" ", (key_or_name or "")).strip().title()


class EmbeddingKNN:
    tier = "embedding_knn"

    def __init__(self, conn, client: EmbeddingsClient, *, k: int = 15, min_neighbors: int = 3):
        self._conn = conn
        self._client = client
        self._k = k
        self._min_neighbors = min_neighbors

    async def _query_vector(self, ctx: TxnContext) -> Optional[List[float]]:
        """Use the stored merchant embedding if present; else embed on the fly.
        Returns None (→ abstain) if embedding is unavailable (Ollama down)."""
        stored = await self._conn.fetchval(
            "SELECT embedding FROM finance.merchants WHERE merchant_key = $1 AND embedding IS NOT NULL",
            ctx.merchant_key,
        )
        if stored is not None:
            return stored
        try:
            return await self._client.embed(_humanize(ctx.merchant_key or ctx.description))
        except EmbeddingError as e:
            logger.warning("EmbeddingKNN: embed failed, abstaining: %s", e)
            return None

    async def classify(self, ctx: TxnContext) -> Decision:
        if not ctx.merchant_key:
            return Decision.abstain(self.tier)

        vec = await self._query_vector(ctx)
        if vec is None:
            return Decision.abstain(self.tier, rationale={"reason": "no_embedding"})

        # Nearest merchants (excluding self) that have a resolvable category:
        # the directory prior, else the majority category of their categorized txns.
        neighbors = await self._conn.fetch(
            """
            SELECT m.merchant_key,
                   COALESCE(m.category_prior_id, mt.majority_category) AS category_id
            FROM finance.merchants m
            LEFT JOIN LATERAL (
                SELECT t.category_id AS majority_category
                FROM finance.transactions t
                WHERE t.merchant_key = m.merchant_key AND t.category_id IS NOT NULL
                GROUP BY t.category_id ORDER BY count(*) DESC, t.category_id LIMIT 1
            ) mt ON true
            WHERE m.embedding IS NOT NULL
              AND m.merchant_key <> $2
              AND COALESCE(m.category_prior_id, mt.majority_category) IS NOT NULL
            ORDER BY m.embedding <=> $1::public.halfvec
            LIMIT $3
            """,
            vec, ctx.merchant_key, self._k,
        )

        if len(neighbors) >= self._min_neighbors:
            votes: dict[int, int] = {}
            for n in neighbors:
                votes[n["category_id"]] = votes.get(n["category_id"], 0) + 1
            winner, count = max(votes.items(), key=lambda kv: (kv[1], -kv[0]))
            agreement = count / len(neighbors)            # R2.3 confidence
            return Decision(
                category_id=winner, confidence=round(agreement, 4), tier=self.tier,
                rationale={
                    "source": "merchant_knn",
                    "neighbors": len(neighbors),
                    "agreement": round(agreement, 4),
                    "neighbor_keys": [n["merchant_key"] for n in neighbors[:5]],
                },
            )

        # Cold-start: too few categorized merchants → nearest category embedding (B2).
        cat = await self._conn.fetchrow(
            "SELECT id, (embedding <=> $1::public.halfvec) AS distance "
            "FROM finance.categories WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> $1::public.halfvec LIMIT 1",
            vec,
        )
        if cat is not None:
            similarity = max(0.0, min(1.0, 1.0 - float(cat["distance"])))
            return Decision(
                category_id=cat["id"], confidence=round(similarity, 4), tier=self.tier,
                rationale={"source": "category_description", "neighbors": len(neighbors)},
            )

        return Decision.abstain(self.tier, rationale={"reason": "insufficient_neighbors",
                                                      "neighbors": len(neighbors)})


async def embed_merchants(client: EmbeddingsClient, pool, *, only_missing: bool = True,
                          batch_size: int = 64) -> dict:
    """Embed normalized merchant strings into finance.merchants.embedding (R2.3).
    Idempotent; reuses the bge-m3 stack. Runs outside the nightly critical section."""
    config = await get_embedding_config(pool)
    version = int(config.get("version", 1))
    embedded = 0
    async with pool.acquire() as conn:
        where = "WHERE embedding IS NULL" if only_missing else ""
        rows = await conn.fetch(
            f"SELECT merchant_key, display_name FROM finance.merchants {where}")
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            texts = [_humanize(r["display_name"] or r["merchant_key"]) for r in batch]
            try:
                vecs = await client.embed_batch(texts)
            except EmbeddingError as e:
                logger.warning("embed_merchants: batch failed, stopping: %s", e)
                break
            for r, v in zip(batch, vecs):
                await conn.execute(
                    "UPDATE finance.merchants SET embedding = $1::public.halfvec, "
                    "embedding_version = $2, updated_at = now() WHERE merchant_key = $3",
                    v, version, r["merchant_key"])
                embedded += 1
    logger.info("embed_merchants: embedded %d merchants (version %d)", embedded, version)
    return {"embedded": embedded}


async def embed_categories(client: EmbeddingsClient, pool) -> dict:
    """Compute one embedding per category (name → humanized) for the kNN cold-start
    fallback (B2). Idempotent (overwrites; categories are few)."""
    config = await get_embedding_config(pool)
    version = int(config.get("version", 1))
    embedded = 0
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, name FROM finance.categories")
        if rows:
            try:
                vecs = await client.embed_batch([_humanize(r["name"]) for r in rows])
            except EmbeddingError as e:
                logger.warning("embed_categories: failed: %s", e)
                return {"embedded": 0, "error": str(e)}
            for r, v in zip(rows, vecs):
                await conn.execute(
                    "UPDATE finance.categories SET embedding = $1::public.halfvec WHERE id = $2",
                    v, r["id"])
                embedded += 1
    logger.info("embed_categories: embedded %d categories (version %d)", embedded, version)
    return {"embedded": embedded}
