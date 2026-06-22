"""ai-finance-insights Task 6 — DB-driven insight config loader (R2.2)."""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.finance_insights.config import load_insight_config
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_loader_returns_seeded_values(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cfg = await load_insight_config(conn)
        assert cfg.insights_enabled is True
        assert cfg.enabled("duplicate_charge") is True
        assert cfg.get("detector.price_creep.min_increase_pct") == 0.15
        assert cfg.get("detector.unusual_spend.mad_multiplier") == 3.0
        assert "retire" in cfg.retirement_keywords
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_missing_db_key_falls_back_to_code_default(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # Remove a seeded row → loader must fall back to the code default.
            await conn.execute(
                "DELETE FROM finance.insight_config WHERE key = 'detector.price_creep.min_history'"
            )
            cfg = await load_insight_config(conn)
        assert cfg.get("detector.price_creep.min_history") == 3  # code default
        # A key absent from both DB and defaults → the provided default.
        assert cfg.get("detector.nope.enabled", "fallback") == "fallback"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_operator_edit_wins_over_default(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE finance.insight_config SET value = '0.25'::jsonb "
                "WHERE key = 'detector.price_creep.min_increase_pct'"
            )
            cfg = await load_insight_config(conn)
        assert cfg.get("detector.price_creep.min_increase_pct") == 0.25
    finally:
        await close_pool()
