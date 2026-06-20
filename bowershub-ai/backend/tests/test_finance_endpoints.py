"""
Unit tests for the finance dashboard endpoints.

Tests the three finance endpoints: summary, balances, and recent-transactions.
Verifies correct SQL result processing, error handling for schema issues,
and the column validation helper.

Validates: Requirements 8.1, 8.2, 8.3, 8.4, 8.5
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import asyncpg
import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool
from backend.routers.dashboard import (
    _finance_error_response,
    _validate_finance_columns,
    finance_summary,
    finance_balances,
    finance_recent_transactions,
)
from backend.services.categorizer import run_categorizer
from backend.tests.semantic_helpers import apply_migrations


# ---------------------------------------------------------------------------
# Real-DB fixture
#
# The success-path tests below run against a fresh ephemeral Postgres DB built
# from the REAL baseline via run_migrations() (not a hand-rolled mini-schema).
# The previous hand-built `finance` schema drifted from production — most
# importantly it gave `finance.transactions` a SERIAL `id` and omitted
# `user_category_override`, which is *why* the R5.1 categorizer bug went
# unnoticed (the nightly UPDATE never ran against the real non-updatable
# public.transactions JOIN view in tests). apply_migrations() sets the
# module-level pool that dashboard.get_pool()/categorizer.get_pool() read, so
# the endpoints and the categorizer hit this DB without any monkeypatching.
#
# Real-schema notes for seeding: finance.accounts.id and finance.transactions.id
# are varchar(128) with no default; finance.transactions.account_id is NOT NULL
# (FK → finance.accounts). finance.categories.id has a sequence default, so
# category inserts may omit id.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def finance_pool(fresh_db, db_settings):
    """Ephemeral DB built from the real baseline; yields the live asyncpg pool.

    apply_migrations() sets the module-level pool consumed by
    dashboard.get_pool() and categorizer.get_pool(), so callers hit this DB
    without any monkeypatching.
    """
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        yield pool
    finally:
        await close_pool()


# ---------------------------------------------------------------------------
# Helper: _finance_error_response
# ---------------------------------------------------------------------------


def test_finance_error_response_structure():
    """Error response has error=True, message from exception, and data=None."""
    err = Exception("column 'foo' does not exist")
    result = _finance_error_response(err)

    assert result["error"] is True
    assert "foo" in result["message"]
    assert result["data"] is None


def test_finance_error_response_with_various_exceptions():
    """Works with different exception types."""
    for exc in [
        ValueError("bad value"),
        RuntimeError("connection lost"),
        KeyError("missing_key"),
    ]:
        result = _finance_error_response(exc)
        assert result["error"] is True
        assert result["data"] is None
        assert len(result["message"]) > 0


# ---------------------------------------------------------------------------
# finance_summary endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finance_summary_success(finance_pool):
    """Summary returns MTD spending/income, top categories, prev month, net change.

    Real-DB: seeds this-month and last-month transactions (using CURRENT_DATE so
    the test is calendar-independent) plus a transfer and an investment that must
    be excluded from the spending/income totals.
    """
    async with finance_pool.acquire() as conn:
        acct = await conn.fetchval(
            "INSERT INTO finance.accounts (id, org_name, account_name) "
            "VALUES (gen_random_uuid()::text, 'Test', 'Checking') RETURNING id"
        )
        cats = {}
        for name in ("Food", "Gas", "Entertainment"):
            # fetch-or-create: some of these names are now seeded by 0023.
            cats[name] = await conn.fetchval(
                "INSERT INTO finance.categories (name) VALUES ($1) "
                "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id",
                name,
            )

        # This month: spending across 3 categories (-750 total), income +3500,
        # plus an excluded transfer and an excluded investment (no category, so
        # they also stay out of the category INNER JOIN).
        this_month = "date_trunc('month', CURRENT_DATE)::date"
        await conn.execute(
            f"""
            INSERT INTO finance.transactions
                (id, account_id, amount, description, category_id, posted_date, is_transfer, is_investment)
            VALUES
                (gen_random_uuid()::text, $4, -400, 'groceries',  $1, {this_month}, false, false),
                (gen_random_uuid()::text, $4, -200, 'fuel',       $2, {this_month}, false, false),
                (gen_random_uuid()::text, $4, -150, 'movie',      $3, {this_month}, false, false),
                (gen_random_uuid()::text, $4,  3500,'paycheck', NULL, {this_month}, false, false),
                (gen_random_uuid()::text, $4, -1000,'xfer',     NULL, {this_month}, true,  false),
                (gen_random_uuid()::text, $4, -500, 'brokerage',NULL, {this_month}, false, true)
            """,
            cats["Food"], cats["Gas"], cats["Entertainment"], acct,
        )

        # Previous month: spending -2000, income +3000.
        prev_month = "(date_trunc('month', CURRENT_DATE) - INTERVAL '1 month')::date"
        await conn.execute(
            f"""
            INSERT INTO finance.transactions
                (id, account_id, amount, description, category_id, posted_date, is_transfer, is_investment)
            VALUES
                (gen_random_uuid()::text, $1, -2000, 'rent',  NULL, {prev_month}, false, false),
                (gen_random_uuid()::text, $1,  3000, 'wages', NULL, {prev_month}, false, false)
            """,
            acct,
        )

    with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
        result = await finance_summary(user={"id": 1})

    assert result["error"] is False
    data = result["data"]
    assert data["mtd_spending"] == 750.00            # transfer + investment excluded
    assert data["mtd_income"] == 3500.00
    assert data["prev_month_spending"] == 2000.00
    assert data["prev_month_income"] == 3000.00
    assert data["net_change"] == -1250.00            # 750 - 2000
    cats_out = data["top_categories"]
    assert [c["category"] for c in cats_out] == ["Food", "Gas", "Entertainment"]
    assert cats_out[0]["total"] == 400.00


@pytest.mark.asyncio
async def test_finance_summary_schema_error():
    """Schema error (missing column) returns error response with HTTP 200."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = Exception(
        'column "posted_date" does not exist'
    )

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_summary(user={"id": 1})

    assert result["error"] is True
    assert "posted_date" in result["message"]
    assert result["data"] is None


@pytest.mark.asyncio
async def test_finance_summary_table_not_found():
    """Missing table returns error response."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.side_effect = Exception(
        'relation "finance.transactions" does not exist'
    )

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_summary(user={"id": 1})

    assert result["error"] is True
    assert "transactions" in result["message"]
    assert result["data"] is None


# ---------------------------------------------------------------------------
# finance_balances endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finance_balances_success(finance_pool):
    """Balances groups accounts by org_name with a net-worth total.

    Real-DB: the live query groups by org_name (there is no 'type' column),
    excludes a hard-coded set of bookkeeping orgs ('Email Receipts', …), and
    orders by org_name, account_name.
    """
    async with finance_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO finance.accounts (id, org_name, account_name, last_balance)
            VALUES
                (gen_random_uuid()::text, 'Chase',          'Checking', 5000),
                (gen_random_uuid()::text, 'Chase',          'Credit',  -2000),
                (gen_random_uuid()::text, 'Ally',           'Savings', 15000),
                (gen_random_uuid()::text, 'Vanguard',       '401k',    50000),
                (gen_random_uuid()::text, 'Email Receipts', 'noise',     999)
            """
        )

    with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
        result = await finance_balances(user={"id": 1})

    assert result["error"] is False
    data = result["data"]
    grouped = data["accounts_by_type"]

    # Grouped by org_name; the bookkeeping org is filtered out.
    assert set(grouped) == {"Chase", "Ally", "Vanguard"}
    assert "Email Receipts" not in grouped

    # Net worth: 5000 + (-2000) + 15000 + 50000 = 68000 (Email Receipts excluded)
    assert data["net_worth"] == 68000.00

    # Chase accounts ordered by account_name: Checking then Credit.
    chase = grouped["Chase"]
    assert [a["name"] for a in chase] == ["Checking", "Credit"]
    assert chase[0]["balance"] == 5000.00
    assert chase[1]["balance"] == -2000.00


@pytest.mark.asyncio
async def test_finance_balances_empty():
    """No accounts returns empty groups and zero net worth."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_balances(user={"id": 1})

    assert result["error"] is False
    assert result["data"]["accounts_by_type"] == {}
    assert result["data"]["net_worth"] == 0.0


@pytest.mark.asyncio
async def test_finance_balances_null_balance(finance_pool):
    """Accounts with a NULL last_balance are excluded entirely.

    Real-DB: the live query has `WHERE last_balance IS NOT NULL`, so a
    null-balance account never reaches the response (the old mock asserted it
    was coerced to 0 — that behavior no longer exists).
    """
    async with finance_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO finance.accounts (id, org_name, account_name, last_balance)
            VALUES
                (gen_random_uuid()::text, 'Chase', 'Checking', NULL),
                (gen_random_uuid()::text, 'Ally',  'Savings',  100)
            """
        )

    with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
        result = await finance_balances(user={"id": 1})

    assert result["error"] is False
    grouped = result["data"]["accounts_by_type"]
    assert "Chase" not in grouped          # null-balance account filtered out
    assert grouped["Ally"][0]["balance"] == 100.0
    assert result["data"]["net_worth"] == 100.0


@pytest.mark.asyncio
async def test_finance_balances_schema_error():
    """Schema error returns graceful error response."""
    mock_conn = AsyncMock()
    mock_conn.fetch.side_effect = Exception(
        'relation "finance.accounts" does not exist'
    )

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_balances(user={"id": 1})

    assert result["error"] is True
    assert "accounts" in result["message"]
    assert result["data"] is None


# ---------------------------------------------------------------------------
# finance_recent_transactions endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finance_recent_transactions_success():
    """Returns last 10 transactions with correct fields."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {
            "amount": Decimal("-45.67"),
            "description": "WALMART SUPERCENTER",
            "category": "Food_Groceries",
            "posted_date": date(2026, 6, 7),
        },
        {
            "amount": Decimal("-12.50"),
            "description": "SHELL OIL 12345",
            "category": "Trans_Gas",
            "posted_date": date(2026, 6, 6),
        },
        {
            "amount": Decimal("3500.00"),
            "description": "PAYROLL DEPOSIT",
            "category": "Income",
            "posted_date": date(2026, 6, 5),
        },
    ]

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_recent_transactions(user={"id": 1})

    assert result["error"] is False
    txns = result["data"]["transactions"]
    assert len(txns) == 3

    # First transaction
    assert txns[0]["amount"] == -45.67
    assert txns[0]["description"] == "WALMART SUPERCENTER"
    assert txns[0]["category"] == "Food_Groceries"
    assert txns[0]["posted_date"] == "2026-06-07"

    # Third transaction (income - positive)
    assert txns[2]["amount"] == 3500.00
    assert txns[2]["category"] == "Income"


@pytest.mark.asyncio
async def test_finance_recent_transactions_empty():
    """No transactions returns empty list."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_recent_transactions(user={"id": 1})

    assert result["error"] is False
    assert result["data"]["transactions"] == []


@pytest.mark.asyncio
async def test_finance_recent_transactions_null_date():
    """Transaction with null posted_date serializes as None."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {
            "amount": Decimal("-10.00"),
            "description": "PENDING CHARGE",
            "category": None,
            "posted_date": None,
        },
    ]

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_recent_transactions(user={"id": 1})

    assert result["error"] is False
    txn = result["data"]["transactions"][0]
    assert txn["posted_date"] is None
    assert txn["category"] is None


@pytest.mark.asyncio
async def test_finance_recent_transactions_schema_error():
    """Schema error returns graceful error response."""
    mock_conn = AsyncMock()
    mock_conn.fetch.side_effect = Exception(
        'column "posted_date" does not exist'
    )

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        with patch("backend.routers.dashboard._validate_finance_columns", new_callable=AsyncMock):
            result = await finance_recent_transactions(user={"id": 1})

    assert result["error"] is True
    assert "posted_date" in result["message"]
    assert result["data"] is None


# ---------------------------------------------------------------------------
# Column validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_finance_columns_logs_missing(caplog):
    """Column validator logs warnings for missing columns."""
    import backend.routers.dashboard as mod

    # Reset the flag so validation runs
    mod._finance_columns_validated = False

    mock_conn = AsyncMock()
    # Return only 'id' and 'amount' for transactions, 'id' for accounts
    mock_conn.fetch.side_effect = [
        [{"column_name": "id"}, {"column_name": "amount"}],
        [{"column_name": "id"}],
    ]

    mock_pool = MagicMock()
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_acquire.__aexit__ = AsyncMock(return_value=None)
    mock_pool.acquire.return_value = mock_acquire

    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        import logging
        with caplog.at_level(logging.WARNING):
            await _validate_finance_columns()

    # Should warn about missing columns
    assert any("missing" in record.message.lower() for record in caplog.records)

    # Reset for other tests
    mod._finance_columns_validated = False


@pytest.mark.asyncio
async def test_validate_finance_columns_runs_once():
    """Validation only runs once (idempotent)."""
    import backend.routers.dashboard as mod

    # Set as already validated
    mod._finance_columns_validated = True

    mock_pool = MagicMock()
    with patch("backend.routers.dashboard.get_pool", return_value=mock_pool):
        await _validate_finance_columns()

    # Pool.acquire should never have been called
    mock_pool.acquire.assert_not_called()

    # Reset for other tests
    mod._finance_columns_validated = False


# ---------------------------------------------------------------------------
# R5.1 — the nightly categorizer's write must persist to finance.transactions
#
# Reproduce-then-fix regression for the silently-dead categorizer: it used to
# UPDATE an *unqualified* `transactions`, which under the runtime role resolves
# to public.transactions — a non-updatable multi-table JOIN view (migration
# 0016, no INSTEAD OF trigger) — so the UPDATE errored and nothing persisted.
# Run against the REAL baseline so public.transactions is the real view and
# finance.transactions has all categorization columns (the old hand-rolled test
# schema had neither, which is why this bug went unnoticed).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_categorizer_r51_reproduce_then_fix(finance_pool):
    async with finance_pool.acquire() as conn:
        acct = await conn.fetchval(
            "INSERT INTO finance.accounts (id, org_name, account_name) "
            "VALUES (gen_random_uuid()::text, 'Test', 'Checking') RETURNING id"
        )
        cat = await conn.fetchval(
            "INSERT INTO finance.categories (name) VALUES ('Food_Groceries') "
            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id"
        )
        txn = await conn.fetchval(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
            "VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, -42.00, 'KROGER #123') RETURNING id",
            acct,
        )

        # (1) Reproduce: the OLD unqualified write targeted public.transactions,
        # a non-updatable JOIN view — the UPDATE raises.
        with pytest.raises(asyncpg.PostgresError):
            await conn.execute(
                "UPDATE public.transactions SET category_id = $1 WHERE id = $2",
                cat, txn,
            )

    # (2) Fix: run_categorizer (now schema-qualified to finance.*) persists the
    # category to finance.transactions. Ollama is stubbed to return a valid label.
    fake_response = '[{"id": "%s", "category": "Food_Groceries"}]' % txn
    with patch(
        "backend.services.categorizer._call_ollama",
        new=AsyncMock(return_value=fake_response),
    ):
        summary = await run_categorizer()

    assert summary["status"] == "completed"
    assert summary["updated"] == 1

    async with finance_pool.acquire() as conn:
        persisted = await conn.fetchval(
            "SELECT category_id FROM finance.transactions WHERE id = $1", txn
        )
    assert persisted == cat
