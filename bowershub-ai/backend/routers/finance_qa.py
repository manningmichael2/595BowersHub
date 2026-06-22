"""Conversational finance Q&A (R1.1, R1.2, R1.4, R1.6, R5.2).

`POST /api/finance/qa` answers a free-text question from the owner's real data by
reusing the `ask_db` sandbox (LLM SQL → validate_select → finance_reader READ
ONLY) and then narrating the *computed* rows through the `FinanceNarrator`
boundary — figures are quoted verbatim, never authored (R1.2). The empty (R1.6)
and out-of-scope (R1.4) cases are answered in code from `ask_db`'s `scope`,
never by the model, so they stay honest and distinct. `sql` + `figures` are
returned for the "reveal the query/figures" disclosure (verifiability).

Auth: read-access via `get_current_user` (the model only ever touches data
through the least-privilege sandbox). The retirement-intent branch is added in
Task 17.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from backend.database import get_pool
from backend.middleware.auth import get_current_user
from backend.services.finance import ask_db
from backend.services.finance_narration import FinanceNarrator

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance-qa"])

# Code-authored messages for the non-data cases — distinct so the UI can tell a
# real "nothing matched" (R1.6) from "I can't see that" (R1.4).
_EMPTY_ANSWER = "No matching financial activity found for that question."
_OUT_OF_SCOPE_ANSWER = (
    "That's outside what I can see — I can only read your finance data, "
    "not other parts of the system."
)


class QARequest(BaseModel):
    question: str


@router.post("/qa")
async def finance_qa(
    body: QARequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    provider = getattr(request.app.state, "model_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Model provider unavailable.")

    result = await ask_db(question, provider=provider)
    scope = result.get("scope")
    sql = result.get("sql_generated")

    if scope == "out_of_scope":
        return {"answer": _OUT_OF_SCOPE_ANSWER, "sql": sql, "figures": [], "scope": "out_of_scope"}
    if scope == "empty":
        return {"answer": _EMPTY_ANSWER, "sql": sql, "figures": [], "scope": "empty"}
    if scope != "in_scope":
        # A genuine SQL error or a validate_select refusal — surface it as a
        # bad-gateway with the reason (single-owner app; the SQL is shown anyway).
        detail = result.get("error", "Could not answer that question.")
        raise HTTPException(status_code=502, detail=detail)

    figures = result.get("results", [])
    answer = await FinanceNarrator(provider).narrate(
        facts=figures, question=question, scope="in_scope"
    )
    return {"answer": answer, "sql": sql, "figures": figures, "scope": "in_scope"}


class RuleParseRequest(BaseModel):
    text: str


@router.post("/rules/parse")
async def parse_rule(
    body: RuleParseRequest,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """NL → a VALIDATED categorization-rule candidate + an affected-count preview
    (R3.1/R3.2/R3.4). Read-only: the candidate is committed separately via the
    require_admin POST /user-rules. A candidate that fails validation → 422."""
    from backend.services.categorization.rules import count_matching
    from backend.services.nl_rules import (
        RuleValidationError, propose_rule_candidate, validate_rule_candidate,
    )

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    provider = getattr(request.app.state, "model_provider", None)
    if provider is None:
        raise HTTPException(status_code=503, detail="Model provider unavailable.")

    raw = await propose_rule_candidate(provider, text)
    try:
        async with get_pool().acquire() as conn:
            validated = await validate_rule_candidate(conn, raw)
            preview = await count_matching(conn, validated.to_user_rule())
    except RuleValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "candidate": validated.to_commit_payload(),
        "category_name": validated.category_name,
        "merchant_key": validated.merchant_key,
        "preview_count": preview,
    }
