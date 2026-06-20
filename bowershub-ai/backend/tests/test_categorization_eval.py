"""Task 4 — eval harness skeleton + labels (R2.7).

Proves the plumbing: 0025 seeds eval_labels (incl. transfer cases) resolved
against the 0023 categories, and the harness scores an arbitrary classifier
callable end-to-end (per-tier accuracy + transfer confusion). The REAL tiers /
full cascade are scored in Task 13 — here a stub classifier stands in.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.categorization.base import Decision, TxnContext
from backend.services.categorization_eval import (
    load_eval_labels,
    score_classifier,
)
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_eval_labels_seeded_and_resolve_to_categories(fresh_db, db_settings):
    """0025 seeds labels whose expected_category_id / transfer flags are populated."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            labels = await load_eval_labels(conn)
        assert len(labels) >= 20
        # Every non-transfer label resolved to a real category id (seeded in 0023).
        spending = [l for l in labels if not l.is_transfer_expected]
        assert all(l.expected_category_id is not None for l in spending)
        # Transfer/debt cases are present (the asymmetric-gate failure modes).
        transfers = [l for l in labels if l.is_transfer_expected]
        assert len(transfers) >= 4
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_seed_is_idempotent(fresh_db, db_settings):
    """Re-applying 0025 against an already-seeded DB inserts nothing (NOT EXISTS guard)."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            before = await conn.fetchval("SELECT count(*) FROM finance.eval_labels")
            from pathlib import Path
            sql = (Path(__file__).resolve().parents[1] / "migrations" / "0025_seed_eval_labels.sql").read_text()
            await conn.execute(sql)
            after = await conn.fetchval("SELECT count(*) FROM finance.eval_labels")
        assert after == before
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_harness_scores_a_stub_classifier(fresh_db, db_settings):
    """The harness runs a classifier over the labels and tallies accuracy +
    transfer confusion. The stub: returns the expected category for groceries,
    flags anything with 'TRANSFER' in the descriptor, abstains otherwise."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            labels = await load_eval_labels(conn)
            groceries_id = await conn.fetchval(
                "SELECT id FROM finance.categories WHERE name = 'Food_Groceries'"
            )

        async def stub(ctx: TxnContext) -> Decision:
            if "TRANSFER" in ctx.description.upper():
                return Decision(category_id=None, confidence=0.95, tier="transfer",
                                rationale={}, is_transfer=True, terminal=True)
            if "COSTCO" in ctx.description.upper() or "KROGER" in ctx.description.upper():
                return Decision(category_id=groceries_id, confidence=0.9,
                                tier="rule", rationale={"model_id": "stub-1"})
            return Decision.abstain("llm")

        report = await score_classifier(stub, labels)

        # Stub got the two grocery rows right via the 'rule' tier.
        assert report.per_tier["rule"].correct == 2
        assert report.per_tier["rule"].n == 2
        assert report.per_model["stub-1"].correct == 2
        # It flagged the two 'TRANSFER ...' descriptors → true positives, no false positives.
        assert report.transfer.tp == 2
        assert report.transfer.fp == 0
        # Plenty abstained (everything else).
        assert report.abstained > 0
        # Report serializes cleanly (for CI / logging).
        assert report.as_dict()["per_tier"]["rule"]["accuracy"] == 1.0
    finally:
        await close_pool()
