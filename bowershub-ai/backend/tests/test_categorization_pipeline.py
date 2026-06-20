"""Task 10 — Pipeline + ConfidenceGate + Writer + nightly orchestration.

Cascade order/short-circuit; per-tier gate (below→queue, above→auto); mid-batch
correction not clobbered (R3.4); double-run no-op + resumable (R5.2); shadow mode
mutates nothing (M4); provenance reconstructs coverage/LLM counts (R5.6); transfer
& investment rows are never assigned a spending category (B-2).
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.categorization.base import Decision, TxnContext
from backend.services.categorization.config import CategorizerConfig, load_config
from backend.services.categorization.learning import record_correction
from backend.services.categorization.orchestrator import categorization_metrics, run_cascade
from backend.services.categorization.pipeline import (
    CategorizationPipeline,
    ConfidenceGate,
    PipelineResult,
    Writer,
)
from backend.tests.semantic_helpers import FakeEmbeddingsClient, apply_migrations


class FakeTier:
    def __init__(self, tier: str, decision: Decision):
        self.tier = tier
        self._d = decision

    async def classify(self, ctx):
        return self._d


def _cfg(**over) -> CategorizerConfig:
    return CategorizerConfig(**over)


def _ctx():
    return TxnContext(txn_id="t", description="X", amount=-5.0, merchant_key="X")


# ---- Pipeline / gate unit tests (no DB) ----

@pytest.mark.asyncio
async def test_short_circuits_on_first_tier_clearing_threshold():
    tiers = [
        FakeTier("transfer", Decision.abstain("transfer")),
        FakeTier("rule", Decision.abstain("rule")),
        FakeTier("merchant_memory", Decision(category_id=10, confidence=0.9, tier="merchant_memory")),
        FakeTier("embedding_knn", Decision(category_id=99, confidence=0.99, tier="embedding_knn")),
    ]
    result = await CategorizationPipeline(tiers, _cfg()).classify(_ctx())
    assert result.decision.tier == "merchant_memory"  # stops before kNN
    assert result.decision.category_id == 10
    assert result.auto_apply is True


@pytest.mark.asyncio
async def test_terminal_rule_short_circuits():
    tiers = [
        FakeTier("rule", Decision(category_id=5, confidence=1.0, tier="rule", terminal=True)),
        FakeTier("merchant_memory", Decision(category_id=10, confidence=0.99, tier="merchant_memory")),
    ]
    result = await CategorizationPipeline(tiers, _cfg()).classify(_ctx())
    assert result.decision.tier == "rule" and result.auto_apply is True


@pytest.mark.asyncio
async def test_transfer_short_circuits_and_gates():
    confident = [FakeTier("transfer", Decision(None, 0.98, "transfer", is_transfer=True, terminal=True))]
    ambiguous = [FakeTier("transfer", Decision(None, 0.5, "transfer", is_transfer=True))]
    r1 = await CategorizationPipeline(confident, _cfg()).classify(_ctx())
    r2 = await CategorizationPipeline(ambiguous, _cfg()).classify(_ctx())
    assert r1.decision.is_transfer and r1.auto_apply is True       # auto-flag
    assert r2.decision.is_transfer and r2.auto_apply is False      # → "transfer?" queue


@pytest.mark.asyncio
async def test_below_threshold_returns_best_candidate_for_queue():
    tiers = [
        FakeTier("merchant_memory", Decision(category_id=10, confidence=0.5, tier="merchant_memory")),
        FakeTier("embedding_knn", Decision(category_id=20, confidence=0.65, tier="embedding_knn")),
        FakeTier("llm", Decision.abstain("llm")),
    ]
    result = await CategorizationPipeline(tiers, _cfg()).classify(_ctx())
    assert result.auto_apply is False
    assert result.decision.category_id == 20  # the more confident sub-threshold guess
    assert result.decision.confidence == 0.65


def test_gate_uses_per_tier_thresholds():
    cfg = _cfg(thresholds={"merchant_memory": 0.8, "embedding_knn": 0.7})
    gate = ConfidenceGate(cfg)
    assert gate.clears(Decision(1, 0.75, "embedding_knn")) is True    # >= 0.7
    assert gate.clears(Decision(1, 0.75, "merchant_memory")) is False  # < 0.8


@pytest.mark.asyncio
async def test_disabled_tier_is_skipped():
    cfg = _cfg(tiers_enabled={"merchant_memory": False, "embedding_knn": True})
    tiers = [
        FakeTier("merchant_memory", Decision(category_id=10, confidence=0.99, tier="merchant_memory")),
        FakeTier("embedding_knn", Decision(category_id=20, confidence=0.99, tier="embedding_knn")),
    ]
    result = await CategorizationPipeline(tiers, cfg).classify(_ctx())
    assert result.decision.tier == "embedding_knn"  # memory skipped


# ---- Writer / orchestration integration tests ----

async def _seed_txn(conn, desc, *, amount=-20.0, is_transfer=False, is_investment=False,
                    merchant_key=None):
    acct = await conn.fetchval(
        "INSERT INTO finance.accounts (id, org_name, account_name) "
        "VALUES (gen_random_uuid()::text, 'T', 'CC') RETURNING id")
    return await conn.fetchval(
        "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, "
        "merchant_key, is_transfer, is_investment) "
        "VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, $2, $3, $4, $5, $6) RETURNING id",
        acct, amount, desc, merchant_key, is_transfer, is_investment)


async def _set_engine(conn, engine):
    await conn.execute(
        "UPDATE finance.categorizer_config SET value = $1::jsonb WHERE key = 'categorizer_engine'",
        f'"{engine}"')


@pytest.mark.asyncio
async def test_writer_guard_blocks_midbatch_correction(fresh_db, db_settings):
    """R3.4: if a correction lands (user_category_override=true) before the write,
    the guarded UPDATE no-ops and the correction survives."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
            other = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Shopping'")
            txn = await _seed_txn(conn, "MID BATCH")
            # Simulate the mid-batch correction.
            await conn.execute(
                "UPDATE finance.transactions SET category_id=$1, user_category_override=true WHERE id=$2",
                cat, txn)
            result = PipelineResult(Decision(category_id=other, confidence=0.95, tier="llm"), True)
            written = await Writer().apply(conn, TxnContext(txn_id=txn, description="MID BATCH",
                                                            amount=-5.0), result, shadow=False)
            persisted = await conn.fetchval(
                "SELECT category_id FROM finance.transactions WHERE id=$1", txn)
        assert written["wrote_category"] is False
        assert persisted == cat  # the correction was NOT clobbered
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_shadow_mutates_nothing_but_logs(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
            txn = await _seed_txn(conn, "SQ *SUNRISE BAKERY", merchant_key="SUNRISE BAKERY")
            await record_correction(conn, category_id=cat, merchant_key="SUNRISE BAKERY")
            await _set_engine(conn, "shadow")

        summary = await run_cascade(pool, embeddings_client=FakeEmbeddingsClient())
        assert summary["engine"] == "shadow" and summary["auto_applied"] == 0

        async with pool.acquire() as conn:
            still_null = await conn.fetchval(
                "SELECT category_id FROM finance.transactions WHERE id=$1", txn)
            logged = await conn.fetchval(
                "SELECT count(*) FROM finance.categorization_decision WHERE transaction_id=$1", txn)
        assert still_null is None        # no mutation in shadow
        assert logged >= 1               # but provenance recorded
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_cascade_applies_and_is_idempotent_with_provenance(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            dining = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
            txn = await _seed_txn(conn, "SQ *SUNRISE BAKERY", merchant_key="SUNRISE BAKERY")
            await record_correction(conn, category_id=dining, merchant_key="SUNRISE BAKERY")
            await _set_engine(conn, "cascade")

        first = await run_cascade(pool, embeddings_client=FakeEmbeddingsClient())
        assert first["auto_applied"] == 1

        async with pool.acquire() as conn:
            persisted = await conn.fetchval(
                "SELECT category_id FROM finance.transactions WHERE id=$1", txn)
            assert persisted == dining
            metrics = await categorization_metrics(conn)
            assert metrics["auto_applied"] >= 1
            assert metrics["per_tier"]["merchant_memory"]["auto_applied"] >= 1

        # Double-run: the row is now categorized → out of the work-set → no-op (R5.2).
        second = await run_cascade(pool, embeddings_client=FakeEmbeddingsClient())
        assert second["transactions_found"] == 0 and second["auto_applied"] == 0
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_transfer_and_investment_rows_never_categorized(fresh_db, db_settings):
    """B-2: is_transfer=true and is_investment=true rows stay out of the work-set."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            dining = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
            xfer = await _seed_txn(conn, "SUNRISE", merchant_key="SUNRISE BAKERY", is_transfer=True)
            invest = await _seed_txn(conn, "SUNRISE", merchant_key="SUNRISE BAKERY", is_investment=True)
            await record_correction(conn, category_id=dining, merchant_key="SUNRISE BAKERY")
            await _set_engine(conn, "cascade")

        summary = await run_cascade(pool, embeddings_client=FakeEmbeddingsClient())
        assert summary["transactions_found"] == 0  # both excluded

        async with pool.acquire() as conn:
            for tid in (xfer, invest):
                cat = await conn.fetchval(
                    "SELECT category_id FROM finance.transactions WHERE id=$1", tid)
                assert cat is None  # never assigned a spending category
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_llm_residue_and_call_metrics(fresh_db, db_settings):
    """A row no earlier tier resolves reaches the LLM; the call is counted (R5.6)."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            wood = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Woodshop'")
            await _seed_txn(conn, "OBSCURE WORKSHOP LLC", merchant_key="OBSCURE WORKSHOP LLC")
            await _set_engine(conn, "cascade")

        async def fake_llm(_prompt):
            return '{"category":"Woodshop","confidence":0.85}'

        summary = await run_cascade(pool, embeddings_client=FakeEmbeddingsClient(),
                                    llm_call_model=fake_llm)
        assert summary["auto_applied"] == 1

        async with pool.acquire() as conn:
            metrics = await categorization_metrics(conn)
            assert metrics["llm_calls"] >= 1
            assert metrics["per_tier"]["llm"]["auto_applied"] >= 1
            cat = await conn.fetchval(
                "SELECT category_id FROM finance.transactions WHERE description='OBSCURE WORKSHOP LLC'")
            assert cat == wood
    finally:
        await close_pool()
