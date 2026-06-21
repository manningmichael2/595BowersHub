"""Transactions explorer query — filters, sort, allocation-aware subtotals/totals."""

from __future__ import annotations

from datetime import date

import pytest

from backend.database import close_pool
from backend.services.splits import create_split
from backend.services.transactions_query import search_transactions
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_search_filters_sort_and_subtotals(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name, account_type) "
                "VALUES ('A1','Bank','Checking','checking') RETURNING id")
            cats = [r["id"] for r in await conn.fetch("SELECT id FROM finance.categories ORDER BY id LIMIT 2")]
            c0, c1 = cats
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, category_id, is_transfer) VALUES "
                "('t1', $1, CURRENT_DATE, -40, 'COSTCO', $2, false),"
                "('t2', $1, CURRENT_DATE, -10, 'UBER',   $3, false),"
                "('t3', $1, CURRENT_DATE, 2000, 'PAYCHECK', $2, false),"
                "('t4', $1, CURRENT_DATE, -500, 'TRANSFER OUT', NULL, true),"
                "('t5', $1, CURRENT_DATE, -25, 'NEEDS CAT', NULL, false)",
                acct, c0, c1)

            # All rows, sorted by amount asc → t4 (-500) first
            res = await search_transactions(conn, sort="amount", order="asc")
            assert res["items"][0]["id"] == "t4"
            assert res["count"] == 5

            # Text filter
            r2 = await search_transactions(conn, q="costco")
            assert [i["id"] for i in r2["items"]] == ["t1"]

            # status=uncategorized → only t5 (t4 is a transfer, excluded)
            r3 = await search_transactions(conn, status="uncategorized")
            assert [i["id"] for i in r3["items"]] == ["t5"]

            # Subtotals (allocation-aware, exclude transfer): spending in c0=40, c1=10,
            # Uncategorized=25; income total=2000, spending total=75 (transfer excluded)
            res_all = await search_transactions(conn, status="all")
            assert res_all["totals"] == {"income": 2000.0, "spending": 75.0}

            # Split t1 (-40) across c0(-30)+c1(-10): total spend unchanged (no double
            # count), and the split parent drops out of the list (children nest).
            await create_split(conn, "t1", [{"category_id": c0, "amount": -30}, {"category_id": c1, "amount": -10}])
            after = await search_transactions(conn, status="all")
            assert after["totals"]["spending"] == 75.0  # unchanged (no double count)
            ids = [i["id"] for i in after["items"]]
            assert "t1" in ids and after["count"] == 5   # split parent stays top-level; children hidden (not extra rows)
    finally:
        await close_pool()
