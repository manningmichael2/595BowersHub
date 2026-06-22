"""ai-finance-insights Task 7 — detectors (R2.2, R2.3).

Plant data, run a single detector, assert exactly the expected candidate(s) with
figures + reason. DB-backed so the real_activity view + grouping run for real.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.database import close_pool
from backend.services.finance_insights.config import load_insight_config
from backend.services.finance_insights import detectors as det
from backend.tests.semantic_helpers import apply_migrations


async def _acct(conn, acct_id="a1"):
    await conn.execute(
        "INSERT INTO finance.accounts (id, account_name) VALUES ($1, 'Checking') "
        "ON CONFLICT (id) DO NOTHING",
        acct_id,
    )
    return acct_id


async def _txn(conn, tid, amount, when, *, merchant=None, acct="a1", category_id=None):
    await conn.execute(
        """
        INSERT INTO finance.transactions
            (id, account_id, posted_date, amount, description, merchant_key, category_id, is_transfer)
        VALUES ($1, $2, $3, $4, 'x', $5, $6, false)
        """,
        tid, acct, when, amount, merchant, category_id,
    )


@pytest.mark.asyncio
async def test_duplicate_charge_one_candidate(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _acct(conn)
            today = date.today()
            await _txn(conn, "d1", -19.99, today - timedelta(days=2), merchant="acme")
            await _txn(conn, "d2", -19.99, today, merchant="acme")
            # An unrelated single charge → not a duplicate.
            await _txn(conn, "x1", -5.00, today, merchant="solo")
            cfg = await load_insight_config(conn)
            cands = await det.detect_duplicate_charge(conn, cfg)
        assert len(cands) == 1
        c = cands[0]
        assert c.merchant_key == "acme"
        assert c.dollar_impact == 19.99
        assert c.figures["amount"] == 19.99 and c.reason  # carries figures + reason
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_price_creep_one_candidate(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _acct(conn)
            base = date.today()
            # Three months at $10, then a jump to $15 (+50%, > 15% threshold).
            await _txn(conn, "p1", -10.00, base - timedelta(days=90), merchant="netflix")
            await _txn(conn, "p2", -10.00, base - timedelta(days=60), merchant="netflix")
            await _txn(conn, "p3", -10.00, base - timedelta(days=30), merchant="netflix")
            await _txn(conn, "p4", -15.00, base, merchant="netflix")
            cfg = await load_insight_config(conn)
            cands = await det.detect_price_creep(conn, cfg)
        assert len(cands) == 1
        c = cands[0]
        assert c.merchant_key == "netflix"
        assert c.figures["latest"] == 15.0 and c.figures["prior_avg"] == 10.0
        assert c.reason
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_unusual_spend_respects_min_history(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _acct(conn)
            cat = await conn.fetchval(
                "INSERT INTO finance.categories (name) VALUES ('Dining') RETURNING id"
            )
            # Only 2 months of history then a spike — below the default min_history (6),
            # so no unusual-spend candidate may be raised.
            base = date.today().replace(day=1)
            for i, amt in enumerate([-50, -55, -500]):
                m = (base - timedelta(days=31 * (2 - i)))
                await _txn(conn, f"u{i}", amt, m, merchant="diner", category_id=cat)
            cfg = await load_insight_config(conn)
            cands = await det.detect_unusual_spend(conn, cfg)
        assert cands == []
    finally:
        await close_pool()
