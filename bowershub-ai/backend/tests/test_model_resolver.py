"""DB-backed tests for the Resolver read cache (spec: dynamic-model-discovery, Task 5).

Covers R4.1 (role aliases resolve), R4.4 (default model), R3.4 (exact-match cost key
+ same-provider normalize fallback + fail-closed dangling alias), and the perf NFR
(no per-call DB round-trip). Runs against ephemeral Postgres with the real chain."""

from __future__ import annotations

import asyncpg
import pytest

from backend.config import Config
from backend.database import init_pool, run_migrations
from backend.services.model_catalog import (
    CatalogRefresh,
    DiscoveredModel,
    DiscoveryResult,
    Resolver,
    get_resolver,
    init_resolver,
    normalize_key,
)

pytestmark = pytest.mark.asyncio


async def _apply_migrations(db_name: str, db_settings: dict) -> asyncpg.Pool:
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test", N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    await run_migrations(pool)
    return pool


class _FakeSource:
    provider = "anthropic"
    def __init__(self, models): self._models = models
    async def discover(self): return DiscoveryResult(models=list(self._models), complete=True)


async def test_all_roles_resolve_to_active_rows_and_default(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        r = Resolver(pool)
        await r.reload()
        assert r.resolve_role("haiku") == "claude-haiku-4-5-20251001"
        assert r.resolve_role("sonnet") == "claude-sonnet-4-6"
        assert r.resolve_role("opus") == "claude-opus-4-5-20251101"
        assert r.resolve_role("local") == "llama3.2:3b"
        for role in ("haiku", "sonnet", "opus", "local"):
            assert r.get(r.resolve_role(role))["is_active"] is True   # R4.1
        assert r.default_chat_model() == "claude-sonnet-4-6"          # R4.4
    finally:
        await pool.close()


async def test_resolution_is_cached_no_per_call_db_hit(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        r = Resolver(pool)
        await r.reload()
        assert r.resolve_role("sonnet") == "claude-sonnet-4-6"
        # mutate the DB WITHOUT reloading — a per-call DB lookup would see the change
        async with pool.acquire() as c:
            await c.execute("UPDATE public.bh_model_aliases SET model_id='claude-haiku-4-5-20251001' WHERE role='sonnet'")
        assert r.resolve_role("sonnet") == "claude-sonnet-4-6"        # still cached → proves no DB round-trip
        await r.reload()
        assert r.resolve_role("sonnet") == "claude-haiku-4-5-20251001"  # picks up the change only on reload
    finally:
        await pool.close()


async def test_dangling_or_inactive_alias_fails_closed(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        r = Resolver(pool)
        async with pool.acquire() as c:
            await c.execute("UPDATE public.bh_model_rates SET is_active=false WHERE model_id='claude-sonnet-4-6'")
        await r.reload()
        got = r.resolve_role("sonnet")
        assert got != "claude-sonnet-4-6"            # never returns the inactive alias target
        assert r.get(got)["is_active"] is True        # fail-closed to an ACTIVE model
        assert "sonnet" in got                        # ...in the same tier (e.g. claude-sonnet-4-5)
    finally:
        await pool.close()


async def test_cost_key_exact_match_bedrock_and_inactive(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        r = Resolver(pool)
        await r.reload()
        # B1: a Bedrock id reads its OWN priced row, not the bare claude-* row
        assert r.row_for_cost("us.anthropic.claude-sonnet-4-5-v1:0")["model_id"] == "us.anthropic.claude-sonnet-4-5-v1:0"
        assert r.row_for_cost("claude-sonnet-4-5")["model_id"] == "claude-sonnet-4-5"
        # normalize fallback only on an exact miss (prefix stripped → same-base row)
        assert normalize_key("anthropic.claude-opus-4-5-20251101") == "claude-opus-4-5-20251101"
        assert r.row_for_cost("anthropic.claude-opus-4-5-20251101")["model_id"] == "claude-opus-4-5-20251101"
        # cost lookup sees INACTIVE rows so historical usage still prices (R1.4 acceptance)
        async with pool.acquire() as c:
            await c.execute("UPDATE public.bh_model_rates SET is_active=false WHERE model_id='claude-opus-4-5'")
        await r.reload()
        assert r.row_for_cost("claude-opus-4-5") is not None
        assert "claude-opus-4-5" not in {x["model_id"] for x in r.list_active()}
    finally:
        await pool.close()


async def test_refresh_invalidate_rebuilds_cache_and_singleton(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        r = await init_resolver(pool)           # exercises the module singleton
        assert get_resolver() is r
        assert r.get("claude-fresh-cache-1") is None
        cr = CatalogRefresh(pool, [_FakeSource([DiscoveredModel("claude-fresh-cache-1", "anthropic", "Fresh")])],
                            invalidate=r.reload)
        await cr.refresh()
        assert r.get("claude-fresh-cache-1") is not None   # invalidate awaited reload repopulated the cache
    finally:
        await pool.close()
