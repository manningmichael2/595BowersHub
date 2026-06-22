"""Task 3 — POST /api/finance/qa (R1.1, R1.2, R1.4, R1.6).

The endpoint chains the real ask_db sandbox to the FinanceNarrator boundary. A
fake ModelProvider serves both model calls in order: first the SQL generation,
then the narration. Run against a fresh migrated DB so ask_db executes for real
under finance_reader.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.database import close_pool, get_pool
from backend.models.message import CompletionResult
from backend.routers.finance_qa import finance_qa, QARequest
from backend.tests.semantic_helpers import apply_migrations


class ScriptedProvider:
    """Returns queued completions in order (SQL-gen call, then narrate call)."""

    def __init__(self, *contents):
        self._queue = list(contents)
        self.calls: list[dict] = []

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        self.calls.append({"system": system, "messages": messages})
        content = self._queue.pop(0)
        return CompletionResult(content=content, model=model, input_tokens=8, output_tokens=5)


def _request(provider):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model_provider=provider)))


async def _seed_account():
    async with get_pool().acquire() as conn:
        await conn.execute(
            "INSERT INTO finance.accounts (id, account_name) VALUES ('acct1', 'Checking') "
            "ON CONFLICT (id) DO NOTHING"
        )


async def _seed_transaction(txn_id: str, amount: float):
    """Insert one finance.transactions row (as the migration/superuser role)."""
    async with get_pool().acquire() as conn:
        await conn.execute(
            """
            INSERT INTO finance.transactions
                (id, account_id, posted_date, amount, description, is_transfer)
            VALUES ($1, 'acct1', CURRENT_DATE, $2, 'COFFEE SHOP', false)
            """,
            txn_id,
            amount,
        )


@pytest.mark.asyncio
async def test_in_scope_answer_exposes_sql_and_figures_matching_direct_aggregate(
    fresh_db, db_settings
):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        await _seed_account()
        await _seed_transaction("t1", -12.50)
        await _seed_transaction("t2", -7.25)

        sql = "SELECT sum(amount) AS total FROM finance.transactions"
        provider = ScriptedProvider(sql, "You spent a total of -19.75 at coffee shops.")

        resp = await finance_qa(
            QARequest(question="how much on coffee?"), _request(provider), user={"id": 1}
        )

        assert resp["scope"] == "in_scope"
        assert resp["sql"] == sql
        # figures are the computed rows, surfaced verbatim for verifiability (R1.2)
        assert resp["figures"] == [{"total": -19.75}]
        # equals a direct aggregate computed independently of the model
        async with pool.acquire() as conn:
            direct = await conn.fetchval("SELECT sum(amount) FROM finance.transactions")
        assert float(direct) == resp["figures"][0]["total"]
        assert "coffee" in resp["answer"].lower()
        # The narrate (2nd) call carried the figures as data, not the SQL prompt.
        assert "READ-ONLY DATA" in provider.calls[1]["messages"][0]["content"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_empty_distinct_from_out_of_scope(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        # Valid, in-scope, but no rows → empty (R1.6). Only one model call (SQL-gen);
        # narrate is skipped because the answer is code-authored.
        empty_provider = ScriptedProvider("SELECT * FROM finance.transactions")
        empty = await finance_qa(
            QARequest(question="any rent?"), _request(empty_provider), user={"id": 1}
        )
        assert empty["scope"] == "empty"
        assert len(empty_provider.calls) == 1

        # Reaches a non-granted table → out_of_scope (R1.4).
        oos_provider = ScriptedProvider("SELECT count(*) FROM public.bh_users")
        oos = await finance_qa(
            QARequest(question="list users"), _request(oos_provider), user={"id": 1}
        )
        assert oos["scope"] == "out_of_scope"

        assert empty["answer"] != oos["answer"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_blank_question_rejected():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await finance_qa(QARequest(question="   "), _request(ScriptedProvider()), user={"id": 1})
    assert exc.value.status_code == 400
