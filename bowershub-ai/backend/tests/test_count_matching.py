"""ai-finance-insights Task 11 — count_matching preview parity (R3.2).

count_matching() must equal the ACTUAL apply count (rows that change), including
the manual-override guard — not the raw predicate-match count. Proven on a
fixture that contains a manually-overridden transaction.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.categorization.rules import (
    UserRule, apply_rule_to_existing, count_matching,
)
from backend.tests.semantic_helpers import apply_migrations


async def _setup(conn):
    await conn.execute("INSERT INTO finance.accounts (id, account_name) VALUES ('a1','Checking')")
    cat = await conn.fetchval("INSERT INTO finance.categories (name) VALUES ('Groceries') RETURNING id")
    # Three 'acme' transactions: two plain, one manually overridden (guard skips it).
    await conn.execute(
        "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, "
        "merchant_key, is_transfer, user_category_override) VALUES "
        "('t1','a1',CURRENT_DATE,-10,'x','acme',false,false),"
        "('t2','a1',CURRENT_DATE,-11,'x','acme',false,false),"
        "('t3','a1',CURRENT_DATE,-12,'x','acme',false,true),"   # overridden
        "('t4','a1',CURRENT_DATE,-13,'x','other',false,false)"  # different merchant
    )
    return cat


@pytest.mark.asyncio
async def test_count_matching_equals_apply_count_with_override(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await _setup(conn)
            candidate = UserRule(id=0, priority=100, category_id=cat, merchant_key="acme")

            preview = await count_matching(conn, candidate)
            assert preview == 2  # t1, t2 — NOT the overridden t3, NOT 'other' t4

            # Persist the same rule and actually apply it.
            rule_id = await conn.fetchval(
                "INSERT INTO finance.user_rules (priority, category_id, merchant_key, is_active) "
                "VALUES (100, $1, 'acme', true) RETURNING id",
                cat,
            )
            result = await apply_rule_to_existing(conn, rule_id)

        assert result["matched"] == 3        # raw predicate: t1, t2, t3
        assert result["updated"] == 2         # guard skips the overridden t3
        assert preview == result["updated"]   # preview == actual apply count (R3.2)
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_count_matching_zero_for_unconditioned_candidate(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _setup(conn)
            inert = UserRule(id=0, priority=100, category_id=1)  # no conditions
            assert await count_matching(conn, inert) == 0
    finally:
        await close_pool()
