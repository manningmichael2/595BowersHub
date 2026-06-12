"""
Task 3 — DB-driven embedding config + chat-picker exclusion (R1.2, R1.4).

Applies the full migration chain (extension pre-created) to a fresh DB, warms a
real Resolver off it, and asserts:
  - the `embed` role resolves to the seeded model (R1.2);
  - get_embedding_config round-trips the seeded JSON (R1.2/R3.4);
  - an embedding model is present in the catalog but ABSENT from the chat picker
    DTO, excluded on the is_embedding flag — not a name match (R1.4).

Validates: R1.2, R1.4, R3.4
"""

from __future__ import annotations

import asyncpg
import pytest

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services.model_catalog import Resolver, get_embedding_config

pytestmark = pytest.mark.asyncio


async def _apply(db_name: str, db_settings: dict):
    conn = await asyncpg.connect(database=db_name, **db_settings)
    try:
        await conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await conn.close()
    pool = await init_pool(
        Config(
            ANTHROPIC_API_KEY="test",
            DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
            DB_NAME=db_name, DB_USER=str(db_settings["user"]),
            DB_PASSWORD=str(db_settings["password"]),
            JWT_SECRET="test", N8N_BASE="http://localhost:5678",
        )
    )
    await run_migrations(pool)
    return pool


async def test_embed_alias_and_config_and_picker_exclusion(fresh_db, db_settings):
    pool = await _apply(fresh_db, db_settings)
    try:
        # --- embed role resolves to the seeded model (R1.2) ---------------
        resolver = Resolver(pool)
        await resolver.reload()
        assert resolver.resolve_role("embed") == "bge-m3"

        # --- embedding_config round-trips (R1.2/R3.4) ---------------------
        cfg = await get_embedding_config(pool)
        assert cfg == {"model": "bge-m3", "dim": 1024, "version": 1, "metric": "cosine"}

        # --- picker exclusion on the flag (R1.4) --------------------------
        public_ids = {m["id"] for m in resolver.list_active_public()}
        catalog_ids = {r["model_id"] for r in resolver.list_active()}
        assert "bge-m3" in catalog_ids, "embed model must remain in the catalog"
        assert "bge-m3" not in public_ids, "embed model must NOT appear in the chat picker"
    finally:
        await close_pool()


async def test_embedding_config_fallback_when_absent(fresh_db, db_settings):
    """A missing/malformed row falls back to the seeded default, never raises."""
    pool = await _apply(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM public.bh_platform_settings WHERE key='embedding_config'")
        cfg = await get_embedding_config(pool)
        assert cfg["model"] == "bge-m3" and cfg["dim"] == 1024 and cfg["version"] == 1
    finally:
        await close_pool()
