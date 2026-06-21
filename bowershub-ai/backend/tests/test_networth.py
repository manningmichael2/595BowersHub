"""Finance-accounting Tasks 5-6 — balance snapshots + consolidated net worth.

Covers R3.1 (account_type classification + NULL excluded), R3.2 (liabilities
subtract via signed balance), R3.3 (include_in_net_worth exclusion), R3.5
(snapshot idempotency), R3.6 (history series), R3.7 (stale flag).
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.accounting.networth import compute_net_worth, net_worth_history
from backend.services.accounting.snapshots import snapshot_all_accounts
from backend.tests.semantic_helpers import apply_migrations


async def _acct(conn, name, atype, bal, *, days_old=0, include=True):
    return await conn.fetchval(
        "INSERT INTO finance.accounts (id, org_name, account_name, account_type, "
        "last_balance, last_balance_date, include_in_net_worth) "
        "VALUES (gen_random_uuid()::text, $1, $1, $2, $3, CURRENT_DATE - $4::int, $5) RETURNING id",
        name, atype, bal, days_old, include)


@pytest.mark.asyncio
async def test_net_worth_classification_and_signs(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _acct(conn, "Checking", "checking", 1000)
            await _acct(conn, "Savings", "savings", 500)
            await _acct(conn, "Visa", "credit_card", -200)        # liability, stored negative
            await _acct(conn, "Untyped", None, 999)               # NULL type → excluded
            await _acct(conn, "Tracker", "savings", 5000, include=False)  # excluded by flag
            nw = await compute_net_worth(conn)
        # 1000 + 500 - 200 = 1300; the untyped (+999) and excluded (+5000) don't count.
        assert nw["net_worth"] == 1300.0
        assert nw["assets"] == 1500.0 and nw["liabilities"] == -200.0
        by_name = {a["name"]: a for a in nw["accounts"]}
        assert by_name["Untyped"]["classification"] == "needs_type"
        assert by_name["Untyped"]["included"] is False
        assert by_name["Visa"]["classification"] == "liability"
        assert "Tracker" not in by_name  # include_in_net_worth=false filtered out
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_stale_flag(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _acct(conn, "Fresh", "checking", 100, days_old=1)
            await _acct(conn, "Old", "checking", 100, days_old=30)  # > stale_balance_days (7)
            nw = await compute_net_worth(conn)
            by = {a["name"]: a for a in nw["accounts"]}
            assert by["Fresh"]["stale"] is False
            assert by["Old"]["stale"] is True
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_snapshots_and_history(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _acct(conn, "Checking", "checking", 1000)
            await _acct(conn, "Visa", "credit_card", -200)
            r1 = await snapshot_all_accounts(conn)
            assert r1["snapshotted"] == 2
            # Idempotent same-day: re-run upserts, no new dates.
            await snapshot_all_accounts(conn)
            distinct = await conn.fetchval("SELECT count(*) FROM finance.balance_snapshots")
            assert distinct == 2
            hist = await net_worth_history(conn)
            assert len(hist) == 1 and hist[0]["net_worth"] == 800.0  # 1000 - 200
    finally:
        await close_pool()
