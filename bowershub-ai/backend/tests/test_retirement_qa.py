"""ai-finance-insights Task 17 — retirement Q&A branch (R4.5)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.database import close_pool, get_pool
from backend.models.message import CompletionResult
from backend.routers.finance_qa import finance_qa, QARequest
from backend.services import retirement as ret
from backend.tests.semantic_helpers import apply_migrations

_BASE = {
    "current_age": 40, "retirement_age": 65, "current_balance": 100000,
    "annual_contribution": 12000, "annual_expenses": 40000,
}


class ScriptedProvider:
    def __init__(self, *contents):
        self._q = list(contents)
        self.calls: list[dict] = []

    async def complete(self, model, messages, max_tokens, tools=None, system=None):
        self.calls.append({"system": system, "messages": messages})
        return CompletionResult(content=self._q.pop(0), model=model, input_tokens=5, output_tokens=5)


def _request(provider):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(model_provider=provider)))


@pytest.mark.asyncio
async def test_retirement_question_routes_to_engine(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        async with get_pool().acquire() as conn:
            await ret.upsert_inputs(conn, _BASE)
        # Only ONE model call (narrate); no SQL-gen, because we never hit ask_db.
        provider = ScriptedProvider("Based on your plan you are roughly on track.")
        resp = await finance_qa(
            QARequest(question="Can I retire at 65?"), _request(provider), user={"id": 1}
        )
        assert resp["scope"] == "retirement"
        assert resp["sql"] is None
        assert len(provider.calls) == 1
        # The narrated facts came from the engine (fire_target present, no SQL).
        assert "fire_target" in provider.calls[0]["messages"][0]["content"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_spending_question_routes_to_ask_db(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        async with get_pool().acquire() as conn:
            await ret.upsert_inputs(conn, _BASE)
        # ask_db SQL-gen returns a query; then narrate. A spending question must NOT
        # be misclassified as retirement.
        provider = ScriptedProvider("SELECT 1 AS n", "You have one row.")
        resp = await finance_qa(
            QARequest(question="How much did I spend on dining last month?"),
            _request(provider), user={"id": 1},
        )
        assert resp["scope"] == "in_scope"
        assert resp["sql"] == "SELECT 1 AS n"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_retirement_question_without_inputs_asks_for_inputs(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        # No inputs saved → must ask for inputs, never fabricate a projection.
        provider = ScriptedProvider()  # must not be called
        resp = await finance_qa(
            QARequest(question="When can I retire?"), _request(provider), user={"id": 1}
        )
        assert resp["scope"] == "needs_inputs"
        assert "inputs" in resp["answer"].lower()
        assert provider.calls == []
    finally:
        await close_pool()
