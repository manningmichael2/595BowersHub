"""Finance-budgets-splits Task 1 — schema (0031) + budget config seed (0032).

Proves the SQL applies from empty (C2), the split columns + parent self-FK
(ON DELETE CASCADE) work, the new columns reach public.transactions, the
public.real_activity view bakes the three exclusions (R2.1/R2.2), and the budget
config seeds (R3.5/R4.2).
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_0031_columns_views_and_grants(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cols = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='finance' AND table_name='transactions'")}
            assert {"parent_id", "is_split"} <= cols
            view_cols = {r["column_name"] for r in await conn.fetch(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='public' AND table_name='transactions'")}
            assert {"parent_id", "is_split"} <= view_cols
            assert await conn.fetchval("SELECT to_regclass('public.real_activity')") is not None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_real_activity_excludes_split_parents_transfers_investments(fresh_db, db_settings):
    """R2.1/R2.2: the view includes split children + normal rows, excludes split
    parents, transfers, and investments."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name) "
                "VALUES (gen_random_uuid()::text, 'T', 'Checking') RETURNING id")
            cat = await conn.fetchval("SELECT id FROM finance.categories LIMIT 1")

            async def mk(amount, **flags):
                cols = "id, account_id, posted_date, amount, description"
                vals = ["gen_random_uuid()::text", "$1", "CURRENT_DATE", "$2", "'x'"]
                params = [acct, amount]
                for i, (k, v) in enumerate(flags.items(), start=3):
                    cols += f", {k}"; vals.append(f"${i}"); params.append(v)
                return await conn.fetchval(
                    f"INSERT INTO finance.transactions ({cols}) VALUES ({','.join(vals)}) RETURNING id", *params)

            normal = await mk(-10)
            await mk(-20, is_transfer=True)
            await mk(-30, is_investment=True)
            parent = await mk(-100, is_split=True)
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, parent_id, category_id) "
                "VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, -100, 'child', $2, $3)", acct, parent, cat)

            ids = {r["id"] for r in await conn.fetch("SELECT id FROM public.real_activity")}
            # normal + child present; transfer, investment, split parent absent
            assert normal in ids
            assert parent not in ids
            total = await conn.fetchval("SELECT COALESCE(SUM(amount),0) FROM public.real_activity")
            assert float(total) == -110.0  # normal -10 + child -100; parent/transfer/investment excluded
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_parent_fk_cascade(fresh_db, db_settings):
    """R1.8: deleting a split parent cascades to its children."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name) "
                "VALUES (gen_random_uuid()::text, 'T', 'Checking') RETURNING id")
            parent = await conn.fetchval(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, is_split) "
                "VALUES ('P', $1, CURRENT_DATE, -50, 'p', true) RETURNING id", acct)
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, parent_id) "
                "VALUES ('C', $1, CURRENT_DATE, -50, 'c', $2)", acct, parent)
            await conn.execute("DELETE FROM finance.transactions WHERE id='P'")
            assert await conn.fetchval("SELECT count(*) FROM finance.transactions WHERE id='C'") == 0
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_0032_seeds_budget_config(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cfg = {r["key"]: r["value"] for r in await conn.fetch(
                "SELECT key, value FROM finance.accounting_config WHERE key LIKE 'budget_%'")}
            assert "budget_warn_ratio" in cfg and "budget_over_ratio" in cfg
    finally:
        await close_pool()
