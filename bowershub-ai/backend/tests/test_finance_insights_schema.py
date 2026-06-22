"""ai-finance-insights Task 4 — insights schema (0034).

DB-backed against the real baseline→head chain: the three tables build from
empty, finance_reader can SELECT them (positive GRANT, R2.4) but still cannot
read the auth tables (negative), the dedupe UNIQUE holds, and re-applying the
migration SQL is a no-op (C2 reproducibility).
"""

from __future__ import annotations

from pathlib import Path

import asyncpg
import pytest

from backend.database import close_pool
from backend.tests.semantic_helpers import apply_migrations

_MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "0034_finance_insights_schema.sql"


@pytest.mark.asyncio
async def test_tables_build_and_dedupe_unique_holds(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            for tbl in ("insights", "insight_runs", "job_runs"):
                assert await conn.fetchval("SELECT to_regclass($1)", f"finance.{tbl}") is not None, tbl

            await conn.execute(
                "INSERT INTO finance.insights (insight_type, merchant_key, period, dollar_impact) "
                "VALUES ('price_creep', 'netflix', '2026-06', 5.00)"
            )
            with pytest.raises(asyncpg.UniqueViolationError):
                await conn.execute(
                    "INSERT INTO finance.insights (insight_type, merchant_key, period) "
                    "VALUES ('price_creep', 'netflix', '2026-06')"
                )
            # A new period for the same (type, merchant) is allowed.
            await conn.execute(
                "INSERT INTO finance.insights (insight_type, merchant_key, period) "
                "VALUES ('price_creep', 'netflix', '2026-07')"
            )
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_finance_reader_can_select_insights_but_not_auth_tables(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE finance_reader")
                # Positive: the explicit GRANT lets the reader see insights (R2.4).
                for tbl in ("insights", "insight_runs", "job_runs"):
                    assert await conn.fetchval(f"SELECT count(*) FROM finance.{tbl}") == 0
                # Negative: still no reach into the auth tables.
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.fetchval("SELECT count(*) FROM public.bh_users")
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_reapplying_migration_is_a_noop(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        sql = _MIGRATION.read_text()
        async with pool.acquire() as conn:
            # Already applied by the chain; running it again must not error.
            await conn.execute(sql)
            await conn.execute(sql)
    finally:
        await close_pool()
