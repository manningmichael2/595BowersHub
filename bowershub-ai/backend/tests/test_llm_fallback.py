"""Task 9 — LLMFallback tier (R2.4) + failure handling (R5.5).

Residue-only classification via resolve_role('categorizer'); parse-failure and
Ollama-down defer to the queue (abstain), never "Other"; the legacy
_parse_response Other-fallback is deleted.
"""

from __future__ import annotations

import inspect

import pytest

from backend.database import close_pool
from backend.services.categorization.base import TxnContext
from backend.services.categorization.llm import LLMFallback, build_llm_tier
from backend.tests.semantic_helpers import apply_migrations


def _leaves():
    return {"Food_Groceries": 10, "Food_Dining": 11, "Trans_Gas": 12}


@pytest.mark.asyncio
async def test_valid_response_maps_to_category_and_confidence():
    async def call(_prompt):
        return '{"category":"Food_Groceries","confidence":0.83}'
    tier = LLMFallback(_leaves(), call_model=call, model_id="llama-test")
    d = await tier.classify(TxnContext(txn_id="t", description="KROGER", amount=-20.0))
    assert d.category_id == 10
    assert d.confidence == 0.83
    assert d.rationale["model_id"] == "llama-test"


@pytest.mark.asyncio
async def test_confidence_clamped_and_markdown_stripped():
    async def call(_prompt):
        return '```json\n{"category":"Trans_Gas","confidence":1.7}\n```'
    tier = LLMFallback(_leaves(), call_model=call)
    d = await tier.classify(TxnContext(txn_id="t", description="SHELL", amount=-40.0))
    assert d.category_id == 12
    assert d.confidence == 1.0  # clamped


@pytest.mark.asyncio
async def test_ollama_down_abstains_to_queue():
    async def call(_prompt):
        return None  # model unavailable
    tier = LLMFallback(_leaves(), call_model=call)
    d = await tier.classify(TxnContext(txn_id="t", description="X", amount=-1.0))
    assert d.category_id is None
    assert d.rationale["reason"] == "model_unavailable"


@pytest.mark.asyncio
async def test_parse_failure_and_unknown_category_abstain_never_other():
    async def garbage(_prompt):
        return "I think this is groceries, probably."
    async def unknown(_prompt):
        return '{"category":"NotARealCategory","confidence":0.9}'
    garbage_tier = LLMFallback(_leaves(), call_model=garbage)
    unknown_tier = LLMFallback(_leaves(), call_model=unknown)
    dg = await garbage_tier.classify(TxnContext(txn_id="t", description="X", amount=-1.0))
    du = await unknown_tier.classify(TxnContext(txn_id="t", description="X", amount=-1.0))
    assert dg.category_id is None and dg.rationale["reason"] == "parse_failure_or_unknown"
    assert du.category_id is None and du.rationale["reason"] == "parse_failure_or_unknown"


@pytest.mark.asyncio
async def test_build_llm_tier_loads_leaves_from_db(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            async def call(_prompt):
                return '{"category":"Woodshop","confidence":0.7}'
            tier = await build_llm_tier(conn, call_model=call, model_id="local")
            wood = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Woodshop'")
            d = await tier.classify(TxnContext(txn_id="t", description="ROCKLER", amount=-50.0))
        assert d.category_id == wood
    finally:
        await close_pool()


def test_legacy_other_fallback_is_deleted():
    """R5.5: the categorizer._parse_response Other-fallback source is gone."""
    import backend.services.categorizer as legacy
    src = inspect.getsource(legacy._parse_response)
    assert "assign all to Other" not in src
    assert "fallback: True" not in src
    # The unknown-category branch now abstains (continue), not other_id.
    assert "never \"Other\"" in src or 'never "Other"' in src
