"""ai-finance-insights Task 9 — nightly runner + gates (R2.1, R2.8)."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.database import close_pool, get_pool
from backend.services.finance_insights import runner as runner_mod
from backend.services.finance_insights.runner import run_insight_agent
from backend.tests.semantic_helpers import apply_migrations


async def _mark_categorizer_done(conn):
    await conn.execute(
        "INSERT INTO finance.job_runs (job_name, status, ran_for, completed_at) "
        "VALUES ('categorizer', 'completed', CURRENT_DATE, now())"
    )


async def _seed_duplicate(conn):
    await conn.execute(
        "INSERT INTO finance.accounts (id, account_name) VALUES ('a1','Checking') "
        "ON CONFLICT (id) DO NOTHING"
    )
    today = date.today()
    for tid, when in (("d1", today - timedelta(days=1)), ("d2", today)):
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, "
            "description, merchant_key, is_transfer) VALUES ($1,'a1',$2,-12.00,'x','acme',false)",
            tid, when,
        )


async def _latest_run(conn):
    return await conn.fetchrow(
        "SELECT status, detected FROM finance.insight_runs ORDER BY id DESC LIMIT 1"
    )


@pytest.mark.asyncio
async def test_skips_not_ready_without_categorizer_watermark(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        res = await run_insight_agent()
        assert res["status"] == "skipped-not-ready"
        async with pool.acquire() as conn:
            assert (await _latest_run(conn))["status"] == "skipped-not-ready"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_kill_switch_records_skipped_disabled(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _mark_categorizer_done(conn)
            await conn.execute(
                "UPDATE finance.insight_config SET value='false'::jsonb WHERE key='insights_enabled'"
            )
        res = await run_insight_agent()
        assert res["status"] == "skipped-disabled"
        async with pool.acquire() as conn:
            assert (await _latest_run(conn))["status"] == "skipped-disabled"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_ready_run_detects_and_records(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _mark_categorizer_done(conn)
            await _seed_duplicate(conn)
        res = await run_insight_agent()
        assert res["status"] == "ran"
        assert res["detected"] >= 1 and res["new"] >= 1
        async with pool.acquire() as conn:
            row = await _latest_run(conn)
            assert row["status"] == "ran" and row["detected"] >= 1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_detector_failure_is_isolated(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _mark_categorizer_done(conn)
            await _seed_duplicate(conn)

        # Break ONE detector; the run must still complete and record 'ran'.
        from backend.services.finance_insights import detectors as det
        async def _boom(conn, cfg):
            raise RuntimeError("price creep boom")
        # Patch the registered detector fn in place.
        for d in runner_mod.DETECTORS:
            if d.insight_type == "price_creep":
                monkeypatch.setattr(d, "fn", _boom)

        res = await run_insight_agent()
        assert res["status"] == "ran"
        async with pool.acquire() as conn:
            assert (await _latest_run(conn))["status"] == "ran"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_single_flight_advisory_lock(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _mark_categorizer_done(conn)
        # Hold the advisory lock on a separate connection → the runner must skip.
        holder = await pool.acquire()
        try:
            await holder.fetchval("SELECT pg_advisory_lock($1)", runner_mod._ADVISORY_LOCK_KEY)
            res = await run_insight_agent()
            assert res["status"] == "skipped-locked"
        finally:
            await holder.fetchval("SELECT pg_advisory_unlock($1)", runner_mod._ADVISORY_LOCK_KEY)
            await pool.release(holder)
    finally:
        await close_pool()
