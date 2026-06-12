"""
Hybrid Retrieval: combines vector similarity with full-text search using RRF.
"""

import logging
from typing import Any, Dict, List, Optional

from backend.database import get_pool
from backend.services.embeddings import EmbeddingsClient, EmbeddingError

logger = logging.getLogger(__name__)

# Only rank rows embedded at the CURRENT version, so a re-embed wave never mixes
# vector spaces (R3.4). Inlined into the vector CTE.
_CURRENT_VERSION_SQL = (
    "(SELECT (value_json->>'version')::int FROM public.bh_platform_settings "
    "WHERE key = 'embedding_config')"
)


class HybridRetriever:
    """
    Hybrid search (vector ANN + full-text) merged with Reciprocal Rank Fusion (RRF).

    Satisfies R3.1, R3.2, R3.3, R3.4. When the query cannot be embedded (Ollama
    down/model missing) it degrades cleanly to FTS-only (R3.3) — the vector CTE is
    omitted entirely, never fed a NULL vector.
    """

    def __init__(self, embeddings_client: EmbeddingsClient, pool):
        self.client = embeddings_client
        self.pool = pool
        self._rrf_k = 60          # RRF constant (R3.2)
        self._overfetch_factor = 3  # vector candidates fetched before RRF/scope (R3.3)

    async def search_hybrid(
        self,
        query: str,
        source_type: str,
        limit: int = 10,
        accessible_workspaces: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        """Hybrid search. `accessible_workspaces` scopes message results (R3.3);
        None = unscoped (caller already authorized)."""
        query_vector = None
        try:
            query_vector = await self.client.embed(query)
        except EmbeddingError as e:
            logger.warning(f"HybridRetriever: embedding failed, FTS-only fallback: {e}")  # R3.3

        overfetch_limit = limit * self._overfetch_factor
        async with self.pool.acquire() as conn:
            if source_type == "message":
                return await self._search_messages(
                    conn, query, query_vector, limit, overfetch_limit, accessible_workspaces
                )
            return await self._search_entities(conn, query, query_vector, limit, overfetch_limit)

    def _vector_cte(self, source_type: str, vec_param: str, limit_param: str) -> str:
        """The vector ANN CTE for hybrid mode (current-version rows only)."""
        return f"""
        vector_search AS (
            SELECT source_id,
                   ROW_NUMBER() OVER (ORDER BY embedding <=> {vec_param}::public.halfvec) AS rank
            FROM public.kb_chunks
            WHERE source_type = '{source_type}'
              AND embedding IS NOT NULL
              AND embedding_version = {_CURRENT_VERSION_SQL}
            ORDER BY embedding <=> {vec_param}::public.halfvec
            LIMIT {limit_param}
        ),"""

    async def _search_messages(self, conn, query, query_vector, limit, overfetch_limit, workspaces):
        if query_vector is not None:
            # hybrid: $1 vec, $2 overfetch, $3 query, $4 rrf_k, $5 workspaces, $6 limit
            sql = f"""
            WITH {self._vector_cte('message', '$1', '$2')}
            fts_search AS (
                SELECT source_id,
                       ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $3)) DESC) AS rank
                FROM public.kb_chunks
                WHERE source_type = 'message' AND fts @@ plainto_tsquery('english', $3)
                ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $3)) DESC
                LIMIT $2
            ),
            hybrid AS (
                SELECT COALESCE(v.source_id, f.source_id) AS source_id,
                       (COALESCE(1.0 / ($4 + v.rank), 0.0) + COALESCE(1.0 / ($4 + f.rank), 0.0)) AS rrf_score
                FROM vector_search v
                FULL OUTER JOIN fts_search f ON v.source_id = f.source_id
            )
            SELECT h.source_id, h.rrf_score, m.content, m.conversation_id, m.role, m.created_at,
                   c.title AS conversation_title, c.workspace_id, w.name AS workspace_name
            FROM hybrid h
            JOIN public.bh_messages m ON m.id = h.source_id
            JOIN public.bh_conversations c ON c.id = m.conversation_id
            JOIN public.bh_workspaces w ON w.id = c.workspace_id
            WHERE ($5::int[] IS NULL OR c.workspace_id = ANY($5))
            ORDER BY h.rrf_score DESC
            LIMIT $6
            """
            rows = await conn.fetch(sql, query_vector, overfetch_limit, query, self._rrf_k, workspaces, limit)
        else:
            # FTS-only degrade (R3.3): $1 query, $2 rrf_k, $3 workspaces, $4 limit, $5 overfetch
            sql = """
            WITH fts_search AS (
                SELECT source_id,
                       ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $1)) DESC) AS rank
                FROM public.kb_chunks
                WHERE source_type = 'message' AND fts @@ plainto_tsquery('english', $1)
                ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $1)) DESC
                LIMIT $5
            )
            SELECT f.source_id, (1.0 / ($2 + f.rank)) AS rrf_score,
                   m.content, m.conversation_id, m.role, m.created_at,
                   c.title AS conversation_title, c.workspace_id, w.name AS workspace_name
            FROM fts_search f
            JOIN public.bh_messages m ON m.id = f.source_id
            JOIN public.bh_conversations c ON c.id = m.conversation_id
            JOIN public.bh_workspaces w ON w.id = c.workspace_id
            WHERE ($3::int[] IS NULL OR c.workspace_id = ANY($3))
            ORDER BY rrf_score DESC
            LIMIT $4
            """
            rows = await conn.fetch(sql, query, self._rrf_k, workspaces, limit, overfetch_limit)
        return [dict(r) for r in rows]

    async def _search_entities(self, conn, query, query_vector, limit, overfetch_limit):
        if query_vector is not None:
            # hybrid: $1 vec, $2 overfetch, $3 query, $4 rrf_k, $5 limit
            sql = f"""
            WITH {self._vector_cte('entity', '$1', '$2')}
            fts_search AS (
                SELECT source_id,
                       ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $3)) DESC) AS rank
                FROM public.kb_chunks
                WHERE source_type = 'entity' AND fts @@ plainto_tsquery('english', $3)
                ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $3)) DESC
                LIMIT $2
            ),
            hybrid AS (
                SELECT COALESCE(v.source_id, f.source_id) AS source_id,
                       (COALESCE(1.0 / ($4 + v.rank), 0.0) + COALESCE(1.0 / ($4 + f.rank), 0.0)) AS rrf_score
                FROM vector_search v
                FULL OUTER JOIN fts_search f ON v.source_id = f.source_id
            )
            SELECT h.source_id, h.rrf_score, e.name, e.summary, e.is_active
            FROM hybrid h
            JOIN public.bh_entities e ON e.id = h.source_id
            WHERE e.is_active = true
            ORDER BY h.rrf_score DESC
            LIMIT $5
            """
            rows = await conn.fetch(sql, query_vector, overfetch_limit, query, self._rrf_k, limit)
        else:
            # FTS-only degrade (R3.3): $1 query, $2 rrf_k, $3 limit, $4 overfetch
            sql = """
            WITH fts_search AS (
                SELECT source_id,
                       ROW_NUMBER() OVER (ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $1)) DESC) AS rank
                FROM public.kb_chunks
                WHERE source_type = 'entity' AND fts @@ plainto_tsquery('english', $1)
                ORDER BY ts_rank_cd(fts, plainto_tsquery('english', $1)) DESC
                LIMIT $4
            )
            SELECT f.source_id, (1.0 / ($2 + f.rank)) AS rrf_score, e.name, e.summary, e.is_active
            FROM fts_search f
            JOIN public.bh_entities e ON e.id = f.source_id
            WHERE e.is_active = true
            ORDER BY rrf_score DESC
            LIMIT $3
            """
            rows = await conn.fetch(sql, query, self._rrf_k, limit, overfetch_limit)
        return [dict(r) for r in rows]
