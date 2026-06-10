"""
Integration test for the ask-db least-privilege sandbox (C1/C7).

ask-db executes LLM-generated SQL under `SET LOCAL ROLE finance_reader` in a
READ ONLY transaction. These tests apply the migration chain (baseline +
0002 lockdown) to a fresh database and assert the security boundary the role
provides: it can read domain tables but NOT the bh_* auth tables, and the
de-escalated session is not superuser.
"""

from __future__ import annotations

import asyncpg
import pytest

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations


pytestmark = pytest.mark.asyncio


async def _migrated_pool(db_name: str, db_settings: dict) -> asyncpg.Pool:
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    await run_migrations(pool)
    return pool


async def test_ask_db_execution_pattern_runs_read_only_as_finance_reader(
    fresh_db, db_settings
):
    """The exact ask_db() execution pattern de-escalates and reads domain data."""
    pool = await _migrated_pool(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET TRANSACTION READ ONLY")
                await conn.execute("SET LOCAL statement_timeout = '5000ms'")
                await conn.execute("SET LOCAL ROLE finance_reader")
                current_user = await conn.fetchval("SELECT current_user")
                is_super = await conn.fetchval("SELECT current_setting('is_superuser')")
                # an allowed domain read works (empty on a fresh DB, but permitted)
                rows = await conn.fetchval("SELECT count(*) FROM finance.transactions")
        assert current_user == "finance_reader"
        assert is_super == "off"
        assert rows == 0
    finally:
        await close_pool()


async def test_finance_reader_cannot_read_auth_tables(fresh_db, db_settings):
    """finance_reader must NOT be able to read bh_users (or other bh_* tables)."""
    pool = await _migrated_pool(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await conn.execute("SET ROLE finance_reader")
            try:
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.fetch("SELECT * FROM public.bh_users")
                with pytest.raises(asyncpg.InsufficientPrivilegeError):
                    await conn.fetch("SELECT * FROM public.bh_refresh_tokens")
            finally:
                await conn.execute("RESET ROLE")
    finally:
        await close_pool()
