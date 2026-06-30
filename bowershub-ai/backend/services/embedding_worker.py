"""
Embedding Worker: periodically reconciles bh_messages and bh_entities into kb_chunks.

Reconcile-only capture (no triggers): each tick compares the source tables to the
chunk store, so no write path can bypass it (R2.4) and all state lives in kb_chunks
so a restart simply resumes (R2.3). One tick:
  1. find dirty/new/edited/retry-due source rows → embed → upsert (R2.2/R2.4/R2.7)
  2. reap orphans — chunks whose source row is gone OR no longer eligible (R2.5)

Transient embed failures back off and dead-letter after `max_attempts` (R2.7); a
genuine content edit re-embeds even a previously dead row (the content-hash gate),
while a permanently-dead row with unchanged content is not retried forever.
"""

import hashlib
import logging
from typing import List, Optional

from backend.database import get_pool
from backend.services.embeddings import EmbeddingsClient, EmbeddingError, DimensionMismatchError
from backend.services.model_catalog import get_embedding_config, resolve_role

logger = logging.getLogger(__name__)


def compute_hash(text: str) -> str:
    """Compute SHA256 hash of text for change detection (R2.4).
    Must match Postgres `encode(digest(text,'sha256'),'hex')` used in the find-work
    SQL — both hash the identical assembled string, so the gate is consistent."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# SQL fragment assembling an entity's embedded text (R2.2: name + summary). Used in
# BOTH the SELECT (so Python embeds it) and the digest() change-check, so they agree.
_ENTITY_CONTENT_SQL = "(e.name || ' ' || COALESCE(e.summary, ''))"
# A list's routable identity = name · type label · [list description] · type description.
# The TYPE description carries the routing anchor (example item terms, see migration
# 0055) so a list routes well even with no per-list description — calibration showed
# the old name·label·list-desc document was too thin (~71%, real mis-routes) because
# real lists rarely have a description. Live item names are still deliberately excluded
# (they churn on every add and would re-embed constantly); the type-level examples are
# stable, so this adds no re-embedding churn. concat_ws drops NULL/empty segments.
_LIST_CONTENT_SQL = (
    "concat_ws(' · ', l.name, NULLIF(t.label, ''), NULLIF(l.description, ''), "
    "NULLIF(t.description, ''))"
)


class EmbeddingWorker:
    """Background worker reconciling source tables into the kb_chunks vector store.

    Satisfies R2.2–R2.7. `max_attempts`/`backoff_base_seconds` are injectable so tests
    can exercise the dead-letter path deterministically."""

    def __init__(self, embeddings_client: EmbeddingsClient, pool,
                 *, batch_size: int = 50, max_attempts: int = 5, backoff_base_seconds: int = 30):
        self.client = embeddings_client
        self.pool = pool
        self._batch_size = batch_size
        self._max_attempts = max_attempts
        self._backoff_base = backoff_base_seconds

    async def run_tick(self):
        """Perform one reconcile tick (find work → embed → reap)."""
        try:
            await self._reconcile_messages()
            await self._reconcile_entities()
            await self._reconcile_lists()
            await self._reap_orphans()
        except Exception as e:
            logger.error(f"EmbeddingWorker tick failed: {e}", exc_info=True)

    # --- find work ----------------------------------------------------------
    async def _reconcile_messages(self):
        """Embed new/edited/retry-due user+assistant messages (R2.2/R2.4/R2.7)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT m.id, m.content, COALESCE(k.attempts, 0) AS attempts
                FROM public.bh_messages m
                LEFT JOIN public.kb_chunks k
                  ON k.source_type = 'message' AND k.source_id = m.id AND k.chunk_index = 0
                WHERE m.role IN ('user', 'assistant')
                  AND {self._dirty_predicate("m.content")}
                ORDER BY m.id
                LIMIT $2
                """,
                self._backoff_base, self._batch_size,
            )
        if rows:
            logger.info(f"EmbeddingWorker: reconciling {len(rows)} messages")
            await self._process_batch("message", rows)

    async def _reconcile_entities(self):
        """Embed new/edited/retry-due active entities (R2.2/R2.4/R2.7)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT e.id, {_ENTITY_CONTENT_SQL} AS content, COALESCE(k.attempts, 0) AS attempts
                FROM public.bh_entities e
                LEFT JOIN public.kb_chunks k
                  ON k.source_type = 'entity' AND k.source_id = e.id AND k.chunk_index = 0
                WHERE e.is_active = true
                  AND {self._dirty_predicate(_ENTITY_CONTENT_SQL)}
                ORDER BY e.id
                LIMIT $2
                """,
                self._backoff_base, self._batch_size,
            )
        if rows:
            logger.info(f"EmbeddingWorker: reconciling {len(rows)} entities")
            await self._process_batch("entity", rows)

    async def _reconcile_lists(self):
        """Embed new/renamed/retype'd lists so the AI can route items to them
        (lists-v2 R4). Archived lists are skipped (and reaped below)."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT l.id, {_LIST_CONTENT_SQL} AS content, COALESCE(k.attempts, 0) AS attempts
                FROM public.bh_lists l
                JOIN public.bh_list_types t ON t.id = l.list_type_id
                LEFT JOIN public.kb_chunks k
                  ON k.source_type = 'list' AND k.source_id = l.id AND k.chunk_index = 0
                WHERE l.is_archived = false
                  AND {self._dirty_predicate(_LIST_CONTENT_SQL)}
                ORDER BY l.id
                LIMIT $2
                """,
                self._backoff_base, self._batch_size,
            )
        if rows:
            logger.info(f"EmbeddingWorker: reconciling {len(rows)} lists")
            await self._process_batch("list", rows)

    def _dirty_predicate(self, content_expr: str) -> str:
        """Rows needing (re)embedding. `$1` = backoff base seconds.

        - no chunk yet (new row);
        - content edited (hash differs) — re-embeds even a previously 'dead' row so an
          edit recovers it;
        - embedding_version behind current (R3.4 version bump);
        - a 'pending' row whose embedding never landed (transient failure) and whose
          backoff window has elapsed — THIS is the retry path Gemini's version lacked.
        A 'dead' row with unchanged content/version is NOT reselected (no infinite retry)."""
        cur_version = (
            "(SELECT (value_json->>'version')::int FROM public.bh_platform_settings "
            "WHERE key = 'embedding_config')"
        )
        return f"""(
            k.id IS NULL
            OR k.content_hash <> encode(digest({content_expr}, 'sha256'), 'hex')
            OR (k.embed_state = 'done' AND k.embedding_version < {cur_version})
            OR (k.embed_state = 'pending' AND k.embedding IS NULL
                AND (k.attempts = 0
                     OR k.updated_at < now() - make_interval(secs => $1 * (2 ^ k.attempts))))
        )"""

    # --- embed + store ------------------------------------------------------
    async def _process_batch(self, source_type: str, items: List):
        """Embed a batch and upsert (R2.1/R2.3). On transient failure the batch's
        attempts increment and rows past max_attempts go 'dead'; a dimension mismatch
        is dead immediately (never stored, R2.7)."""
        config = await get_embedding_config(self.pool)
        model = resolve_role("embed")
        version = int(config.get("version", 1))

        texts = [item["content"] for item in items]
        embeddings = None
        error_msg = None
        permanent = False
        try:
            embeddings = await self.client.embed_batch(texts)
        except DimensionMismatchError as e:
            logger.error(f"Embedding dimension mismatch: {e}")
            error_msg, permanent = str(e), True
        except EmbeddingError as e:
            logger.warning(f"Embedding batch failed: {e}")
            error_msg = str(e)
        except Exception as e:
            logger.exception("Unexpected error during embedding batch")
            error_msg = f"Unexpected error: {e}"

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                for i, item in enumerate(items):
                    content = item["content"]
                    content_hash = compute_hash(content)
                    if embeddings is not None and i < len(embeddings):
                        await conn.execute(
                            """
                            INSERT INTO public.kb_chunks
                                (source_type, source_id, chunk_index, content, content_hash,
                                 embedding, embedding_model, embedding_version, embed_state,
                                 attempts, last_error, updated_at)
                            VALUES ($1, $2, 0, $3, $4, $5, $6, $7, 'done', 0, NULL, now())
                            ON CONFLICT (source_type, source_id, chunk_index) DO UPDATE SET
                                content = EXCLUDED.content,
                                content_hash = EXCLUDED.content_hash,
                                embedding = EXCLUDED.embedding,
                                embedding_model = EXCLUDED.embedding_model,
                                embedding_version = EXCLUDED.embedding_version,
                                embed_state = 'done', attempts = 0, last_error = NULL,
                                updated_at = now()
                            """,
                            source_type, item["id"], content, content_hash,
                            embeddings[i], model, version,
                        )
                    else:
                        # failure: bump attempts; dead if permanent or over the cap (R2.7)
                        attempts = int(item["attempts"]) + 1
                        state = "dead" if (permanent or attempts >= self._max_attempts) else "pending"
                        await conn.execute(
                            """
                            INSERT INTO public.kb_chunks
                                (source_type, source_id, chunk_index, content, content_hash,
                                 embed_state, attempts, last_error, updated_at)
                            VALUES ($1, $2, 0, $3, $4, $5, $6, $7, now())
                            ON CONFLICT (source_type, source_id, chunk_index) DO UPDATE SET
                                content = EXCLUDED.content,
                                content_hash = EXCLUDED.content_hash,
                                embed_state = EXCLUDED.embed_state,
                                attempts = EXCLUDED.attempts,
                                last_error = EXCLUDED.last_error,
                                embedding = NULL, embedding_version = NULL,
                                updated_at = now()
                            """,
                            source_type, item["id"], content, content_hash,
                            state, attempts, (error_msg or "")[:2000],
                        )

    # --- delete consistency -------------------------------------------------
    async def _reap_orphans(self):
        """Delete chunks whose source row is gone OR no longer eligible (R2.5):
        a hard-deleted message, or a deleted/soft-deleted (is_active=false) entity —
        so a deactivated entity stops being semantically searchable."""
        async with self.pool.acquire() as conn:
            deleted = await conn.execute(
                """
                DELETE FROM public.kb_chunks k
                WHERE k.source_type = 'message'
                  AND NOT EXISTS (SELECT 1 FROM public.bh_messages m WHERE m.id = k.source_id)
                """
            )
            if " 0" not in deleted:
                logger.info(f"EmbeddingWorker: reaped {deleted.split()[-1]} orphaned message chunks")

            deleted = await conn.execute(
                """
                DELETE FROM public.kb_chunks k
                WHERE k.source_type = 'entity'
                  AND NOT EXISTS (
                      SELECT 1 FROM public.bh_entities e
                      WHERE e.id = k.source_id AND e.is_active = true
                  )
                """
            )
            if " 0" not in deleted:
                logger.info(f"EmbeddingWorker: reaped {deleted.split()[-1]} orphaned entity chunks")

            # Lists: reap chunks for a deleted OR archived list, so the router can
            # never match a dead/archived list (lists-v2 R4).
            deleted = await conn.execute(
                """
                DELETE FROM public.kb_chunks k
                WHERE k.source_type = 'list'
                  AND NOT EXISTS (
                      SELECT 1 FROM public.bh_lists l
                      WHERE l.id = k.source_id AND l.is_archived = false
                  )
                """
            )
            if " 0" not in deleted:
                logger.info(f"EmbeddingWorker: reaped {deleted.split()[-1]} orphaned list chunks")


# Helper to be called by apscheduler
async def run_embedding_worker():
    """Singleton-like runner for the EmbeddingWorker."""
    try:
        from backend.config import load_config
        config = load_config()
        pool = get_pool()

        # Guard: only run once kb_chunks exists (R1.5 — pre-migration boots no-op).
        async with pool.acquire() as conn:
            table_exists = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'kb_chunks'
                )
                """
            )
            if not table_exists:
                return

        client = EmbeddingsClient(config.OLLAMA_URL, pool)
        worker = EmbeddingWorker(client, pool)
        await worker.run_tick()
    except Exception as e:
        logger.error(f"Error in background embedding worker: {e}")
