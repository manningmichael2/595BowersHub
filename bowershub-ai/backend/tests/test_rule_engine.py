"""Task 6 — RuleEngine tier (R2.1).

Priority ordering / first-match-wins; amount-range and account/merchant matching;
terminal rules; apply-to-existing re-runs the predicate over history (guarded).
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.categorization.base import TxnContext
from backend.services.categorization.rules import (
    RuleEngine,
    UserRule,
    apply_rule_to_existing,
    build_rule_engine,
)
from backend.tests.semantic_helpers import apply_migrations


def _ctx(desc="", amount=0.0, merchant_key=None, account_id=None) -> TxnContext:
    return TxnContext(txn_id="t1", description=desc, amount=amount,
                      merchant_key=merchant_key, account_id=account_id)


@pytest.mark.asyncio
async def test_priority_first_match_wins():
    """Lower priority number wins; both rules match the same txn."""
    engine = RuleEngine([
        UserRule(id=2, priority=200, category_id=20, merchant_key="COSTCO"),
        UserRule(id=1, priority=100, category_id=10, merchant_key="COSTCO"),
    ])
    d = await engine.classify(_ctx(merchant_key="COSTCO"))
    assert d.category_id == 10
    assert d.terminal is True and d.confidence == 1.0
    assert d.rationale["rule_id"] == 1


@pytest.mark.asyncio
async def test_amount_range_and_regex_match():
    engine = RuleEngine([
        UserRule(id=1, priority=100, category_id=10,
                 description_regex=r"AMAZON", amount_min=-100.0, amount_max=-50.0),
    ])
    assert (await engine.classify(_ctx(desc="AMAZON MKTPL", amount=-75.0))).category_id == 10
    # outside the amount range → no match → abstain
    assert (await engine.classify(_ctx(desc="AMAZON MKTPL", amount=-10.0))).category_id is None
    # description doesn't match → abstain
    assert (await engine.classify(_ctx(desc="TARGET", amount=-75.0))).category_id is None


@pytest.mark.asyncio
async def test_empty_rule_is_inert():
    """A rule with no conditions must not match everything."""
    engine = RuleEngine([UserRule(id=1, priority=100, category_id=10)])
    assert (await engine.classify(_ctx(desc="ANYTHING", amount=-5.0))).category_id is None


@pytest.mark.asyncio
async def test_account_scoped_rule(fresh_db, db_settings):
    """account_id condition only matches that account; loaded from the DB."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name) "
                "VALUES (gen_random_uuid()::text, 'T', 'Checking') RETURNING id")
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='House_Utilities'")
            await conn.execute(
                "INSERT INTO finance.user_rules (priority, category_id, account_id, description_regex) "
                "VALUES (100, $1, $2, 'DTE')", cat, acct)
            engine = await build_rule_engine(conn)

        assert (await engine.classify(_ctx(desc="DTE ENERGY", account_id=acct))).category_id == cat
        assert (await engine.classify(_ctx(desc="DTE ENERGY", account_id="other"))).category_id is None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_apply_to_existing_is_guarded(fresh_db, db_settings):
    """Apply-to-existing categorizes matching rows but never clobbers a manual override."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            acct = await conn.fetchval(
                "INSERT INTO finance.accounts (id, org_name, account_name) "
                "VALUES (gen_random_uuid()::text, 'T', 'CC') RETURNING id")
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Groceries'")
            for desc, override, key in [
                ("COSTCO WHSE", False, "COSTCO"),
                ("COSTCO GAS", False, "COSTCO"),
                ("COSTCO MANUAL", True, "COSTCO"),   # user-overridden → must be skipped
            ]:
                await conn.execute(
                    "INSERT INTO finance.transactions (id, account_id, posted_date, amount, "
                    "description, merchant_key, user_category_override) "
                    "VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, -20.00, $2, $3, $4)",
                    acct, desc, key, override)
            rule_id = await conn.fetchval(
                "INSERT INTO finance.user_rules (priority, category_id, merchant_key) "
                "VALUES (100, $1, 'COSTCO') RETURNING id", cat)

            result = await apply_rule_to_existing(conn, rule_id)
            assert result["matched"] == 3      # all three match the predicate
            assert result["updated"] == 2      # but the overridden one is not written

            categorized = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions WHERE category_id = $1", cat)
            assert categorized == 2
    finally:
        await close_pool()
