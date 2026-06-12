"""
Integration tests for migration 0010_semantic_memory.sql.

Requires a pgvector-capable Postgres (pgvector/pgvector:pg16) reachable via the
DB_* env vars — the `run-db-tests-locally` pattern with the upgraded image.

Two paths, both exercising the REAL `database.run_migrations()` runner:
  - happy path: the extension is pre-created (mimicking the superuser cutover,
    R4.1) → 0010 applies as the connecting role; kb_chunks + indexes + the
    embed alias / embedding_config seeds all land.
  - R1.5 guard: WITHOUT the extension, the first-statement guard fires and the
    runner aborts with the actionable remediation message — no half-apply.

Validates: R1.2, R1.3, R1.4, R1.5, R2.1, R2.5
"""

from __future__ import annotations

import asyncpg
import pytest

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations

pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
    )


async def _drop_vector(db_name: str, db_settings: dict) -> None:
    """Remove the extension the fixture pre-creates, to exercise the R1.5 guard."""
    conn = await asyncpg.connect(database=db_name, **db_settings)
    try:
        await conn.execute("DROP EXTENSION IF EXISTS vector")
    finally:
        await conn.close()


async def test_0010_applies_with_extension_present(fresh_db, db_settings):
    # fresh_db fixture pre-creates the vector extension (mirrors the cutover)
    pool = await init_pool(_config(fresh_db, db_settings))
    try:
        await run_migrations(pool)
        async with pool.acquire() as conn:
            applied = {
                r["filename"]
                for r in await conn.fetch("SELECT filename FROM public.bh_migrations")
            }
            assert "0010_semantic_memory.sql" in applied

            # --- kb_chunks shape (R2.1) -----------------------------------
            cols = {
                r["column_name"]: r["data_type"]
                for r in await conn.fetch(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = 'kb_chunks'
                    """
                )
            }
            for c in (
                "source_type", "source_id", "chunk_index", "content",
                "content_hash", "embedding", "embedding_model",
                "embedding_version", "fts", "embed_state", "last_error",
            ):
                assert c in cols, f"kb_chunks missing column {c}"

            # embedding is halfvec(1024)
            dim = await conn.fetchval(
                """
                SELECT a.atttypmod
                FROM pg_attribute a
                JOIN pg_class c ON c.oid = a.attrelid
                WHERE c.relname = 'kb_chunks' AND a.attname = 'embedding'
                """
            )
            assert dim == 1024, f"embedding dim should be 1024, got {dim}"

            # --- indexes present ------------------------------------------
            idx = {
                r["indexname"]
                for r in await conn.fetch(
                    "SELECT indexname FROM pg_indexes WHERE tablename = 'kb_chunks'"
                )
            }
            assert "kb_chunks_embedding_idx" in idx       # partial HNSW (R3.1)
            assert "kb_chunks_fts_idx" in idx             # GIN (R3.2)
            assert "kb_chunks_source_lookup_idx" in idx   # joins / reap
            assert "kb_chunks_pending_idx" in idx         # worker drain
            assert "kb_chunks_source_unique" in idx       # UNIQUE constraint's index

            # --- DB-driven config seeded (R1.2) ---------------------------
            alias = await conn.fetchval(
                "SELECT model_id FROM public.bh_model_aliases WHERE role = 'embed'"
            )
            assert alias == "bge-m3"

            cfg = await conn.fetchval(
                "SELECT value_json FROM public.bh_platform_settings WHERE key = 'embedding_config'"
            )
            import json
            cfg = json.loads(cfg) if isinstance(cfg, str) else cfg
            assert cfg == {"model": "bge-m3", "dim": 1024, "version": 1, "metric": "cosine"}

            # --- picker-exclusion flag (R1.4) -----------------------------
            is_embed = await conn.fetchval(
                "SELECT is_embedding FROM public.bh_model_rates WHERE model_id = 'bge-m3'"
            )
            assert is_embed is True
    finally:
        await close_pool()


async def test_0010_guard_fires_without_extension(fresh_db, db_settings):
    """R1.5: no extension → loud remediation, transaction rolls back (no kb_chunks)."""
    await _drop_vector(fresh_db, db_settings)
    pool = await init_pool(_config(fresh_db, db_settings))
    try:
        with pytest.raises(SystemExit) as exc:
            await run_migrations(pool)
        msg = str(exc.value)
        assert "0010_semantic_memory.sql" in msg
        assert "pgvector extension is missing" in msg
        assert "semantic-memory-cutover.md" in msg

        # no half-apply: kb_chunks must not exist
        async with pool.acquire() as conn:
            exists = await conn.fetchval(
                "SELECT to_regclass('public.kb_chunks')"
            )
            assert exists is None
            recorded = await conn.fetchval(
                "SELECT 1 FROM public.bh_migrations WHERE filename = '0010_semantic_memory.sql'"
            )
            assert recorded is None
    finally:
        await close_pool()
