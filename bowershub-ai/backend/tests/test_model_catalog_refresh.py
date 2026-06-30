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
        # Set the instant discover() begins, so a concurrency test can wait for
        # the task to actually be *inside* discover() (deterministic) instead of
        # guessing with a fixed sleep.
        self.entered = asyncio.Event()

    async def discover(self) -> DiscoveryResult:
        self.calls += 1
        self.entered.set()
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
            assert float(new["input_cost_per_mtok"]) == 3.00           # no rule matches → _infer_pricing floor
    finally:
        await pool.close()


async def test_provisional_pricing_from_rules_table(fresh_db, db_settings):
    """0006: new models get provisional prices from the operator-curated
    bh_model_price_rules table, not the stale _infer_pricing ladder. Opus → 5/25
    (current-tier rule, NOT the old 15/75), Ollama → 0/0 (provider rule, NOT 3/15),
    unmatched → the _infer_pricing floor. Still flagged for operator review (R3.2)."""
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        src_anthropic = FakeSource("anthropic", [
            _dm("claude-opus-4-9-20260601", max_input_tokens=1000000),  # opus rule → 5/25
            _dm("claude-mystery-2", max_input_tokens=200000),           # no rule → floor 3/15
        ])
        src_ollama = FakeSource("ollama", [_dm("phi4:14b", provider="ollama")])  # provider rule → 0/0
        await CatalogRefresh(pool, [src_anthropic, src_ollama]).refresh(trigger="admin")
        async with pool.acquire() as c:
            opus = await c.fetchrow(
                "SELECT input_cost_per_mtok, output_cost_per_mtok, needs_price_confirmation "
                "FROM public.bh_model_rates WHERE model_id='claude-opus-4-9-20260601'")
            assert (float(opus["input_cost_per_mtok"]), float(opus["output_cost_per_mtok"])) == (5.00, 25.00)
            assert opus["needs_price_confirmation"] is True            # rule sets the value, not the confirmation
            local = await c.fetchrow(
                "SELECT input_cost_per_mtok, output_cost_per_mtok "
                "FROM public.bh_model_rates WHERE model_id='phi4:14b'")
            assert (float(local["input_cost_per_mtok"]), float(local["output_cost_per_mtok"])) == (0.00, 0.00)
            unknown = await c.fetchval(
                "SELECT input_cost_per_mtok FROM public.bh_model_rates WHERE model_id='claude-mystery-2'")
            assert float(unknown) == 3.00                              # _infer_pricing floor (no rule)
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
        # Deterministic: wait until t1 is actually inside discover() (lock held,
        # parked at the gate) rather than assuming one scheduler tick gets it there
        # — refresh() acquires the DB pool first, so a fixed sleep is racy (flaked
        # the backend CI job intermittently).
        await gated.entered.wait()
        t2 = asyncio.create_task(cr.refresh(trigger="admin"))
        # Drain ready callbacks so t2 runs as far as it can — which is up to the
        # single-flight lock t1 holds. No wall-clock wait, so no CI-load flake.
        for _ in range(10):
            await asyncio.sleep(0)
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
