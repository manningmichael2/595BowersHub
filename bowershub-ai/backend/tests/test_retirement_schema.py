"""ai-finance-insights Task 14 — retirement schema (0036) + config seed (0037)."""

from __future__ import annotations

import asyncpg
import pytest

from backend.database import close_pool
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_singleton_inputs_and_grants(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # Singleton: the first row inserts as id=1; a second is rejected.
            await conn.execute(
                "INSERT INTO finance.retirement_inputs (current_age, retirement_age) VALUES (40, 65)"
            )
            with pytest.raises(asyncpg.PostgresError):
                await conn.execute(
                    "INSERT INTO finance.retirement_inputs (current_age, retirement_age) VALUES (41, 66)"
                )
            # id is forced to 1.
            assert await conn.fetchval("SELECT id FROM finance.retirement_inputs") == 1

            # Positive GRANT: finance_reader (the ask_db/Q&A role) can read inputs.
            async with conn.transaction():
                await conn.execute("SET LOCAL ROLE finance_reader")
                assert await conn.fetchval("SELECT count(*) FROM finance.retirement_inputs") == 1
                assert await conn.fetchval("SELECT count(*) FROM finance.retirement_scenarios") == 0
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_config_seeds_and_is_idempotent(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            rows = {r["key"]: r["value"] for r in await conn.fetch(
                "SELECT key, value FROM finance.retirement_config")}
            assert rows["nominal_return"] == 0.07
            assert rows["withdrawal_rate"] == 0.04
            assert rows["end_age"] == 95
            # Re-apply the seed → no duplicates / no clobber.
            from pathlib import Path
            sql = (Path(__file__).resolve().parents[1] / "migrations"
                   / "0037_seed_retirement_config.sql").read_text()
            await conn.execute(sql)
            assert await conn.fetchval("SELECT count(*) FROM finance.retirement_config") == 4
    finally:
        await close_pool()
