"""Task 7 — MerchantMemory tier + LearningService (R2.2, R3).

A corrected merchant is categorized on the next occurrence with NO model call;
reinforcement raises confidence; a chat-path correction lands in merchant_memory
(B-1 redirect); the 0018 trigger is gone and category_aliases is intact; the
forward-migration of category_examples is idempotent.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.categorization.base import TxnContext
from backend.services.categorization.learning import record_correction
from backend.services.categorization.memory import MerchantMemory, memory_confidence
from backend.tests.semantic_helpers import apply_migrations


def test_confidence_is_monotone_in_reinforcement():
    c1 = memory_confidence(1, None)
    c3 = memory_confidence(3, None)
    c10 = memory_confidence(10, None)
    assert c1 < c3 < c10 <= 0.95


@pytest.mark.asyncio
async def test_correction_sticks_without_model_call(fresh_db, db_settings):
    """record_correction → MerchantMemory returns the learned category next time."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
            await record_correction(conn, category_id=cat, merchant_key="SUNRISE BAKERY",
                                    source="review")

            tier = MerchantMemory(conn)
            d = await tier.classify(TxnContext(txn_id="t1", description="SQ *SUNRISE BAKERY",
                                               amount=-6.0, merchant_key="SUNRISE BAKERY"))
        assert d.category_id == cat
        assert d.tier == "merchant_memory"
        assert d.rationale["source"] == "merchant_memory"
        # An unknown merchant abstains (so the cascade continues to kNN/LLM).
        async with pool.acquire() as conn:
            d2 = await MerchantMemory(conn).classify(
                TxnContext(txn_id="t2", description="X", amount=-1.0, merchant_key="UNKNOWN"))
        assert d2.category_id is None
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_reinforcement_raises_confidence(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Shopping'")
            await record_correction(conn, category_id=cat, merchant_key="TARGET", source="review")
            first = (await MerchantMemory(conn).classify(
                TxnContext(txn_id="t", description="TARGET", amount=-5.0, merchant_key="TARGET"))).confidence
            for _ in range(4):
                await record_correction(conn, category_id=cat, merchant_key="TARGET", source="review")
            later = (await MerchantMemory(conn).classify(
                TxnContext(txn_id="t", description="TARGET", amount=-5.0, merchant_key="TARGET"))).confidence
        assert later > first
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_category_prior_used_when_no_learned_signal(fresh_db, db_settings):
    """A directory category_prior (e.g. MCC cold-start) is a weaker fallback signal."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Groceries'")
            await conn.execute(
                "INSERT INTO finance.merchants (merchant_key, display_name, category_prior_id) "
                "VALUES ('COSTCO', 'Costco', $1)", cat)
            d = await MerchantMemory(conn).classify(
                TxnContext(txn_id="t", description="COSTCO", amount=-50.0, merchant_key="COSTCO"))
        assert d.category_id == cat
        assert d.rationale["source"] == "category_prior"
        assert d.confidence < memory_confidence(1, None)  # weaker than a real correction
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_chat_path_correction_lands_in_merchant_memory(fresh_db, db_settings):
    """B-1: the chat-skill writer (category_override) now reinforces merchant_memory."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        import backend.services.category_override as co

        async with pool.acquire() as conn:
            cat = await conn.fetchrow("SELECT id, name FROM finance.categories WHERE name='Woodshop'")

        # categorize_merchant uses get_pool(); apply_migrations set the global pool.
        result = await co.categorize_merchant("ROCKLER", "Woodshop")
        assert result.get("success")

        async with pool.acquire() as conn:
            mem = await conn.fetchrow(
                "SELECT category_id, times_reinforced FROM finance.merchant_memory "
                "WHERE merchant_key = 'ROCKLER'")
        assert mem is not None
        assert mem["category_id"] == cat["id"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_trigger_dropped_aliases_intact(fresh_db, db_settings):
    """0026 removed the 0018 trigger/function; category_aliases (M1) is untouched."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        from backend.services.normalization import lookup_category_alias
        async with pool.acquire() as conn:
            trig = await conn.fetchval(
                "SELECT count(*) FROM pg_trigger WHERE tgname = 'trg_learn_from_manual_override'")
            fn = await conn.fetchval(
                "SELECT count(*) FROM pg_proc WHERE proname = 'fn_learn_from_manual_override'")
            # The table + its reader survive (M1). On fresh_db the 0018 seed is
            # empty (categories aren't seeded until 0023), so seed one and resolve.
            cat = await conn.fetchrow("SELECT id, name FROM finance.categories WHERE name='Food_Dining'")
            await conn.execute(
                "INSERT INTO finance.category_aliases (alias, category_id) VALUES ('bar', $1) "
                "ON CONFLICT DO NOTHING", cat["id"])
            resolved = await lookup_category_alias(conn, "bar")
        assert trig == 0
        assert fn == 0
        assert resolved == cat["name"]  # category_aliases table + reader intact
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_forward_migration_idempotent(fresh_db, db_settings):
    """Re-applying 0026 with category_examples populated does not double-count."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        from pathlib import Path
        sql = (Path(__file__).resolve().parents[1] / "migrations" /
               "0026_learning_service_cutover.sql").read_text()
        async with pool.acquire() as conn:
            cat = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
            await conn.execute(
                "INSERT INTO finance.category_examples (description_pattern, category_id, times_reinforced) "
                "VALUES ('STARBUCKS', $1, 3)", cat)
            await conn.execute(sql)
            first = await conn.fetchval(
                "SELECT times_reinforced FROM finance.merchant_memory WHERE merchant_key='STARBUCKS'")
            await conn.execute(sql)  # re-apply
            second = await conn.fetchval(
                "SELECT times_reinforced FROM finance.merchant_memory WHERE merchant_key='STARBUCKS'")
        assert first == 3 and second == 3  # ON CONFLICT DO NOTHING — no double-count
    finally:
        await close_pool()
