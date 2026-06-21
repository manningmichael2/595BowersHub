"""Regression: investment flagging must work on the real varchar transaction id.

`flag_investments_in_db` previously bound the matched ids as `$1::int[]`, but
`finance.transactions.id` is `character varying` (e.g. `TRN-<uuid>`), so the
UPDATE errored on every match. At ingest the call is wrapped in a try/except that
swallows the error (simplefin_sync), so investment flagging silently failed on new
data — investment rows then leaked into the categorizer and were mislabeled as
Income. This test reproduces the cast bug (it raises pre-fix) and pins the fix.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.investment_detector import flag_investments_in_db
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_flag_investments_handles_varchar_ids(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name) "
                "VALUES (gen_random_uuid()::text, 'T', 'Brokerage') RETURNING id")
            # String id mirroring prod (the int[] cast crashed on exactly this).
            inv_id = "TRN-invest-0001"
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
                "VALUES ($1, $2, CURRENT_DATE, -500.00, 'Investment: VTSAX')", inv_id, acct)
            # A non-investment row must stay unflagged.
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
                "VALUES ('TRN-grocery-0001', $1, CURRENT_DATE, -42.00, 'KROGER #1')", acct)

        # Pre-fix this raises (asyncpg cannot encode 'TRN-...' as int4[]).
        result = await flag_investments_in_db(window_days=30)
        assert result["flagged"] == 1

        async with pool.acquire() as conn:
            assert await conn.fetchval(
                "SELECT is_investment FROM finance.transactions WHERE id=$1", inv_id) is True
            assert await conn.fetchval(
                "SELECT is_investment FROM finance.transactions WHERE id='TRN-grocery-0001'") is False
    finally:
        await close_pool()
