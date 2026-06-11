"""DB-backed tests for CatalogRefresh (spec: dynamic-model-discovery, Task 4).

Runs against an ephemeral Postgres (conftest `fresh_db`) with the real migration
chain (incl. 0005). Covers R1.1 (persist), R3.1 (price preservation), R3.2
(provisional flag), R1.4 (churn-safe + alias-protected + provider-scoped
deactivation), R2.4 (incomplete fetch deactivates nothing), R2.5 (single-flight,
idempotent, audited)."""

from __future__ import annotations

import asyncio

import asyncpg
import pytest

from backend.config import Config
from backend.database import init_pool, run_migrations
from backend.services.model_catalog import (
    CatalogRefresh,
    DiscoveredModel,
    DiscoveryResult,
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


class FakeSource:
    def __init__(self, provider, models, complete=True, gate: asyncio.Event = None):
        self.provider = provider
        self._models = models
        self._complete = complete
        self.gate = gate
        self.calls = 0

    async def discover(self) -> DiscoveryResult:
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        return DiscoveryResult(models=list(self._models), complete=self._complete)


def _dm(model_id, provider="anthropic", **kw):
    return DiscoveredModel(model_id, provider, kw.pop("display_name", model_id), **kw)


async def test_new_model_persisted_and_flagged_existing_price_preserved(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        # operator corrects an existing model's price
        async with pool.acquire() as c:
            await c.execute(
                "UPDATE public.bh_model_rates SET input_cost_per_mtok=9.99, output_cost_per_mtok=99.99 "
                "WHERE model_id='claude-sonnet-4-6'"
            )
        src = FakeSource("anthropic", [
            _dm("claude-sonnet-4-6", display_name="Renamed Sonnet", max_input_tokens=1000000,
                supports_thinking=True),                  # existing → caps refresh, price preserved
            _dm("claude-brandnew-9", max_input_tokens=200000),  # new → inserted + flagged
        ])
        summary = await CatalogRefresh(pool, [src]).refresh(trigger="admin")
        assert summary.added == 1 and summary.price_flagged == 1

        async with pool.acquire() as c:
            existing = await c.fetchrow(
                "SELECT input_cost_per_mtok, output_cost_per_mtok, display_name, supports_thinking, "
                "needs_price_confirmation FROM public.bh_model_rates WHERE model_id='claude-sonnet-4-6'")
            assert float(existing["input_cost_per_mtok"]) == 9.99      # R3.1 preserved
            assert float(existing["output_cost_per_mtok"]) == 99.99
            assert existing["display_name"] == "Renamed Sonnet"        # caps refreshed
            assert existing["supports_thinking"] is True
            assert existing["needs_price_confirmation"] is False       # not re-flagged

            new = await c.fetchrow(
                "SELECT input_cost_per_mtok, needs_price_confirmation, is_active "
                "FROM public.bh_model_rates WHERE model_id='claude-brandnew-9'")
            assert new["is_active"] is True
            assert new["needs_price_confirmation"] is True             # R3.2 flagged
            assert float(new["input_cost_per_mtok"]) == 3.00           # provisional heuristic (default tier)
    finally:
        await pool.close()


async def test_deactivation_churn_alias_and_provider_scoping(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as c:
            await c.execute(
                "INSERT INTO public.bh_model_rates (provider, model_id, display_name, "
                "input_cost_per_mtok, output_cost_per_mtok) VALUES "
                "('anthropic','claude-legacy-x','Legacy X',3,15), "
                "('ollama','phantom:9b','Phantom',0,0)")
        # complete anthropic source that does NOT include legacy-x (it returns the alias targets)
        src = FakeSource("anthropic", [
            _dm("claude-haiku-4-5-20251001"), _dm("claude-sonnet-4-6"), _dm("claude-opus-4-5-20251101"),
        ], complete=True)
        cr = CatalogRefresh(pool, [src])

        # 1st & 2nd refresh: legacy-x missed but still active (< stale_misses=3)
        await cr.refresh(); await cr.refresh()
        async with pool.acquire() as c:
            r = await c.fetchrow("SELECT is_active, missed_fetch_count FROM public.bh_model_rates WHERE model_id='claude-legacy-x'")
            assert r["is_active"] is True and r["missed_fetch_count"] == 2
        # 3rd refresh: crosses the threshold → deactivated
        s3 = await cr.refresh()
        async with pool.acquire() as c:
            assert (await c.fetchval("SELECT is_active FROM public.bh_model_rates WHERE model_id='claude-legacy-x'")) is False
            # alias target absent-from-source is NEVER deactivated (alias protection)
            assert (await c.fetchval("SELECT is_active FROM public.bh_model_rates WHERE model_id='claude-sonnet-4-6'")) is True
            # provider scoping: a complete anthropic-only fetch never touches ollama rows
            assert (await c.fetchval("SELECT is_active FROM public.bh_model_rates WHERE model_id='phantom:9b'")) is True
        # legacy-x deactivated (>=1; the legacy bare seed rows claude-sonnet-4-5/opus-4-5 also age out, which is correct)
        assert s3.deactivated >= 1
    finally:
        await pool.close()


async def test_incomplete_fetch_deactivates_nothing(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as c:
            await c.execute("INSERT INTO public.bh_model_rates (provider, model_id, display_name, "
                            "input_cost_per_mtok, output_cost_per_mtok) VALUES ('anthropic','claude-legacy-y','Y',3,15)")
        src = FakeSource("anthropic", [_dm("claude-sonnet-4-6")], complete=False)  # API hiccup
        for _ in range(3):
            await CatalogRefresh(pool, [src]).refresh()
        async with pool.acquire() as c:
            r = await c.fetchrow("SELECT is_active, missed_fetch_count FROM public.bh_model_rates WHERE model_id='claude-legacy-y'")
            assert r["is_active"] is True and r["missed_fetch_count"] == 0   # never touched on incomplete fetches
    finally:
        await pool.close()


async def test_single_flight_and_audit_log(fresh_db, db_settings):
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        gate = asyncio.Event()
        gated = FakeSource("anthropic", [_dm("claude-sonnet-4-6")], gate=gate)
        cr = CatalogRefresh(pool, [gated])   # one instance → one lock shared by both calls

        t1 = asyncio.create_task(cr.refresh(trigger="scheduled"))
        await asyncio.sleep(0)               # t1 acquires the lock, calls discover(), blocks at the gate
        t2 = asyncio.create_task(cr.refresh(trigger="admin"))
        await asyncio.sleep(0.02)
        assert gated.calls == 1              # t2 is blocked on the lock — its discover() hasn't run (R2.5 single-flight)
        gate.set()
        await t1
        await t2
        assert gated.calls == 2              # t2 proceeded only after t1 released the lock

        async with pool.acquire() as c:
            assert (await c.fetchval("SELECT count(*) FROM public.bh_model_refresh_log")) == 2   # both audited (R2.5)
            last = await c.fetchrow("SELECT added, deactivated FROM public.bh_model_refresh_log ORDER BY id DESC LIMIT 1")
            assert last["added"] == 0        # second run is a no-op (sonnet-4-6 already present)
    finally:
        await pool.close()
