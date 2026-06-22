"""
Task 2 — ask_db scope classification + governed model call (R1.1, R1.4, R1.5, R1.6).

The SQL-execution sandbox is unchanged; these tests assert the new behaviour:
  - a query that reaches a non-granted table → ``scope == "out_of_scope"`` (R1.4),
    classified from the asyncpg sqlstate, never the model;
  - a valid query that matches no rows → ``scope == "empty"`` (R1.6);
  - a query that fails for a non-scope reason (division by zero) → a generic
    error, NOT ``out_of_scope``;
  - rows → ``scope == "in_scope"`` and the model call is cost-logged to
    ``api_usage_log`` (R1.5).

Run against a fresh migrated DB so the real ``finance_reader`` grants apply.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.models.message import CompletionResult
from backend.services.finance import ask_db
from backend.tests.semantic_helpers import apply_migrations


class CannedSQLProvider:
    """Returns a fixed SQL string as the model's SQL generation, recording calls."""

    def __init__(self, sql: str):
        self._sql = sql
        self.calls = 0

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        self.calls += 1
        return CompletionResult(content=self._sql, model=model, input_tokens=9, output_tokens=4)


@pytest.mark.asyncio
async def test_out_of_scope_when_query_hits_non_granted_table(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        # bh_users is an auth table in public; finance_reader has no SELECT on it.
        result = await ask_db(
            "show me users", provider=CannedSQLProvider("SELECT count(*) FROM public.bh_users")
        )
        assert result["scope"] == "out_of_scope"
        assert "error" not in result
        assert result["results"] == []
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_empty_when_valid_query_matches_no_rows(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        # finance.transactions is granted + on the search_path; a fresh DB has none.
        result = await ask_db(
            "any coffee spend?", provider=CannedSQLProvider("SELECT * FROM transactions")
        )
        assert result["scope"] == "empty"
        assert result["results"] == []
        assert "error" not in result
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_non_scope_execution_error_is_generic_not_out_of_scope(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        # Passes validate_select (a single SELECT) but raises at execution with
        # sqlstate 22012 (division_by_zero) — a real error, not a scope boundary.
        result = await ask_db("break it", provider=CannedSQLProvider("SELECT 1/0 AS boom"))
        assert result.get("scope") != "out_of_scope"
        assert "error" in result
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_in_scope_rows_and_cost_logged(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        result = await ask_db("one", provider=CannedSQLProvider("SELECT 1 AS n"))
        assert result["scope"] == "in_scope"
        assert result["results"] == [{"n": 1}]

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT model, cost_usd FROM public.api_usage_log "
                "WHERE workflow_name = 'bowershub-ai/finance_ask_db'"
            )
        assert len(rows) == 1
        assert rows[0]["cost_usd"] is not None and float(rows[0]["cost_usd"]) > 0
    finally:
        await close_pool()
