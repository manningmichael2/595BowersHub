"""Task 2 — finance-categorization schema migrations (0022/0023) + the B1
privacy-safe `categorizer` role default.

DB-backed checks run against the real baseline→head chain via apply_migrations()
on an ephemeral DB (the migrator/app privilege split is covered separately by
test_migrate_as_app_role.py; here DB_USER is superuser, so this proves the SQL
is valid and applies from empty — C2).
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services import model_catalog
from backend.tests.semantic_helpers import apply_migrations


def test_categorizer_role_fallback_is_local(monkeypatch):
    """B1: with no warmed resolver, resolve_role('categorizer') must stay on a
    LOCAL model — never the hosted 'chat' fallback (which would send txn data
    off-box)."""
    monkeypatch.setattr(model_catalog, "_resolver", None)
    resolved = model_catalog.resolve_role("categorizer")
    assert resolved == model_catalog._FALLBACK_ROLE_MODEL["local"]
    assert resolved != model_catalog._FALLBACK_ROLE_MODEL["chat"]
    assert not resolved.startswith("claude-")  # not a hosted Anthropic model


@pytest.mark.asyncio
async def test_0022_0023_apply_seed_and_columns(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # New finance tables exist.
            for tbl in (
                "merchants", "normalization_rules", "mcc_categories", "user_rules",
                "merchant_memory", "categorization_decision", "eval_labels",
                "categorizer_config",
            ):
                exists = await conn.fetchval(
                    "SELECT to_regclass($1) IS NOT NULL", f"finance.{tbl}"
                )
                assert exists, f"finance.{tbl} missing"

            # Category seed (B2): the full live tree, with hierarchy intact.
            n_cats = await conn.fetchval("SELECT count(*) FROM finance.categories")
            assert n_cats == 25
            parent = await conn.fetchval(
                "SELECT p.name FROM finance.categories c "
                "JOIN finance.categories p ON p.id = c.parent_id "
                "WHERE c.name = 'Trans_Gas'"
            )
            assert parent == "Transportation"

            # Additive columns.
            for tbl, col in (
                ("transactions", "merchant_key"),
                ("transactions", "categorized_by_tier"),
                ("transactions", "categorization_confidence"),
                ("accounts", "account_type"),       # R6.2 prerequisite
                ("categories", "embedding"),         # B2 cold-start kNN
            ):
                has_col = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='finance' AND table_name=$1 AND column_name=$2)",
                    tbl, col,
                )
                assert has_col, f"finance.{tbl}.{col} missing"

            # Config defaults; feature-gate dark by default.
            engine = await conn.fetchval(
                "SELECT value FROM finance.categorizer_config WHERE key='categorizer_engine'"
            )
            assert engine == "legacy"  # asyncpg decodes the jsonb value
            n_cfg = await conn.fetchval("SELECT count(*) FROM finance.categorizer_config")
            assert n_cfg >= 5

            # B1: the categorizer alias is seeded and points at a local (non-hosted) model.
            cat_model = await conn.fetchval(
                "SELECT model_id FROM public.bh_model_aliases WHERE role='categorizer'"
            )
            assert cat_model is not None
            assert not cat_model.startswith("claude-")

            # MCC starter map resolved to real category ids.
            n_mcc = await conn.fetchval("SELECT count(*) FROM finance.mcc_categories")
            assert n_mcc >= 20
            mcc_grocery = await conn.fetchval(
                "SELECT c.name FROM finance.mcc_categories m "
                "JOIN finance.categories c ON c.id = m.category_id WHERE m.mcc='5411'"
            )
            assert mcc_grocery == "Food_Groceries"

            # The public.transactions view was extended (ask-db visibility).
            for col in ("merchant_key", "account_type", "categorization_confidence"):
                in_view = await conn.fetchval(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema='public' AND table_name='transactions' AND column_name=$1)",
                    col,
                )
                assert in_view, f"public.transactions view missing {col}"
    finally:
        await close_pool()
