"""Task 13 — eval harness as a CI regression gate (R2.7), threshold calibration,
and the shadow→cascade gate plumbing.

This test runs in the ordinary backend CI job, so it IS the regression gate that
fires "whenever the role or thresholds change": it scores the full cascade over
finance.eval_labels and asserts baselines. The deterministic transfer baseline
needs no model; the end-to-end accuracy check uses an oracle LLM stub so it stays
deterministic in CI (the live model A/B per categorizer role is the manual step in
docs/finance-categorization-cutover.md).
"""

from __future__ import annotations

import json
import re

import pytest

from backend.database import close_pool
from backend.services.categorization.config import load_config
from backend.services.categorization_eval import (
    load_eval_labels,
    score_cascade,
    set_engine,
    write_thresholds,
)
from backend.tests.semantic_helpers import FakeEmbeddingsClient, apply_migrations

# Regression baselines. Tightening these intentionally is fine; a drop below them
# fails CI and flags a categorization regression.
TRANSFER_RECALL_MIN = 0.8
TRANSFER_PRECISION_MIN = 1.0   # the asymmetric gate must never false-positive a transfer
CASCADE_ACCURACY_MIN = 0.9     # with a correct model, residue must be applied


async def _none_llm(_prompt):
    return None


@pytest.mark.asyncio
async def test_transfer_detection_baseline_no_model(fresh_db, db_settings):
    """Deterministic transfer detection over the labeled set — no model needed."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        report = await score_cascade(pool, embeddings_client=FakeEmbeddingsClient(),
                                     llm_call_model=_none_llm)
        assert report.transfer.recall >= TRANSFER_RECALL_MIN, report.as_dict()
        assert report.transfer.precision >= TRANSFER_PRECISION_MIN, report.as_dict()
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_cascade_applies_llm_residue_with_oracle(fresh_db, db_settings):
    """With a correct categorizer model, the cascade auto-applies the residue —
    guards the pipeline→gate→writer wiring end-to-end and keeps the gate green."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            labels = await load_eval_labels(conn)
            id_to_name = {
                r["id"]: r["name"]
                for r in await conn.fetch("SELECT id, name FROM finance.categories")
            }
        # Oracle: read the description out of the prompt, answer with the label's
        # expected leaf category at high confidence.
        desc_to_cat = {
            l.description: id_to_name.get(l.expected_category_id)
            for l in labels if not l.is_transfer_expected and l.expected_category_id
        }

        async def oracle(prompt: str):
            m = re.search(r'"description":\s*"((?:[^"\\]|\\.)*)"', prompt)
            if not m:
                return None
            desc = json.loads(f'"{m.group(1)}"')
            cat = desc_to_cat.get(desc)
            return json.dumps({"category": cat, "confidence": 0.9}) if cat else None

        report = await score_cascade(pool, embeddings_client=FakeEmbeddingsClient(),
                                     llm_call_model=oracle)
        assert report.accuracy >= CASCADE_ACCURACY_MIN, report.as_dict()
        assert report.per_model  # per-model accuracy recorded (R2.4 A/B basis)
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_calibrate_thresholds_and_flip_engine(fresh_db, db_settings):
    """Calibrated thresholds persist to config; the engine gate flips and reloads."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            await write_thresholds(conn, {"rule": 1.0, "merchant_memory": 0.75,
                                          "embedding_knn": 0.72, "llm": 0.65, "transfer": 0.9})
            await set_engine(conn, "shadow")
            cfg = await load_config(conn)
        assert cfg.engine == "shadow"
        assert cfg.threshold("llm") == 0.65
        assert cfg.threshold("merchant_memory") == 0.75
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_invalid_engine_rejected(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            with pytest.raises(ValueError):
                await set_engine(conn, "live")  # not a valid engine
    finally:
        await close_pool()
