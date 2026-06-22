"""ai-finance-insights Task 12 — NL→rule parse/validate/preview (R3.1-R3.4, R2.6)."""

from __future__ import annotations

import pytest

from backend.database import close_pool, get_pool
from backend.models.message import CompletionResult, ToolCall
from backend.services.categorization.rules import count_matching, apply_rule_to_existing
from backend.services.nl_rules import (
    RuleValidationError, propose_rule_candidate, validate_rule_candidate,
)
from backend.tests.semantic_helpers import apply_migrations


class ToolProvider:
    """Returns a single propose_candidate tool call with the given arguments."""

    def __init__(self, arguments):
        self._args = arguments

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        return CompletionResult(
            content="", model=model, input_tokens=5, output_tokens=5,
            tool_calls=[ToolCall(id="t", name="propose_candidate", arguments=self._args)],
        )


async def _seed(conn):
    await conn.execute("INSERT INTO finance.accounts (id, account_name) VALUES ('a1','Checking')")
    cat = await conn.fetchval("INSERT INTO finance.categories (name) VALUES ('Groceries') RETURNING id")
    # Two Whole Foods charges: a small one (rule applies) and a >$200 one (excluded
    # by amount_min = -200, i.e. "unless over $200").
    await conn.execute(
        "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, "
        "merchant_key, is_transfer) VALUES "
        "('w1','a1',CURRENT_DATE,-30,'x','whole foods',false),"
        "('w2','a1',CURRENT_DATE,-300,'x','whole foods',false)"
    )
    return cat


@pytest.mark.asyncio
async def test_parse_whole_foods_rule_preview_matches_apply(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await _seed(conn)
            provider = ToolProvider(
                {"merchant": "whole foods", "category": "Groceries",
                 "amount_min": -200, "amount_max": None}
            )
            raw = await propose_rule_candidate(provider, "Whole Foods as Groceries unless over $200")
            validated = await validate_rule_candidate(conn, raw)

            assert validated.category_id == cat
            assert validated.merchant_key == "whole foods"
            assert validated.amount_min == -200

            preview = await count_matching(conn, validated.to_user_rule())
            assert preview == 1  # w1 only; w2 (-300) excluded by amount_min

            # Commit it and confirm the affected count equals the preview (R3.2).
            rule_id = await conn.fetchval(
                "INSERT INTO finance.user_rules (priority, category_id, merchant_key, amount_min, is_active) "
                "VALUES ($1,$2,'whole foods',-200,true) RETURNING id",
                validated.priority, cat,
            )
            applied = await apply_rule_to_existing(conn, rule_id)
        assert applied["updated"] == preview
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_abusive_candidate_rejected_no_unbounded_write(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await _seed(conn)
            # Unknown category → rejected.
            with pytest.raises(RuleValidationError):
                await validate_rule_candidate(conn, {"merchant": "whole foods", "category": "DROP TABLE"})
            # Merchant that resolves to nothing → rejected (no unbounded scope).
            with pytest.raises(RuleValidationError):
                await validate_rule_candidate(conn, {"merchant": "', '", "category": "Groceries"})
            # Empty merchant → rejected (would match everything).
            with pytest.raises(RuleValidationError):
                await validate_rule_candidate(conn, {"merchant": "", "category": "Groceries"})
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_insight_to_rule_action_creates_user_rule(fresh_db, db_settings):
    """R2.6: the 'always categorize {merchant} as {category}' action mints a rule."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await _seed(conn)
            # Mirrors what the InsightReview action posts to /user-rules.
            rule_id = await conn.fetchval(
                "INSERT INTO finance.user_rules (priority, category_id, merchant_key, is_active) "
                "VALUES (100, $1, 'whole foods', true) RETURNING id",
                cat,
            )
            assert rule_id is not None
            count = await conn.fetchval(
                "SELECT count(*) FROM finance.user_rules WHERE merchant_key='whole foods'"
            )
        assert count == 1
    finally:
        await close_pool()
