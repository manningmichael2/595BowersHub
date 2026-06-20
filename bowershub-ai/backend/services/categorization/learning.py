"""LearningService (R3) — replaces the 0018 AFTER-UPDATE trigger.

A correction (review API or chat skill) calls `record_correction`, which
upserts/strengthens finance.merchant_memory keyed on the **normalized
merchant_key** (R3.1/R3.2) and appends a decision-log row. MerchantMemory (tier 2)
then consults it deterministically, so the correction sticks without any LLM cost
next time.

Why a service call, not a trigger (§10-T2): a trigger can't compute the
normalized key without re-implementing the DB rules in SQL, fires mid-batch (a
concurrency foot-gun), and is hard to test. The accepted cost is that corrections
made out-of-band via raw db_browser SQL won't auto-learn — corrections flow
through the API/skill path by design.
"""

from __future__ import annotations

import logging
from typing import Optional

from ..merchant_normalizer import MerchantNormalizer, build_normalizer

logger = logging.getLogger(__name__)


async def record_correction(conn, *, category_id: int,
                            merchant_key: Optional[str] = None,
                            description: Optional[str] = None,
                            transaction_id: Optional[str] = None,
                            source: str = "review",
                            normalizer: Optional[MerchantNormalizer] = None) -> dict:
    """Reinforce the learned signal for a merchant.

    Provide either `merchant_key` (already normalized) or `description` (will be
    normalized via the DB rules). Upserts finance.merchant_memory (+1 reinforce,
    bump recency) and appends a finance.categorization_decision row for provenance.
    Returns {"merchant_key", "category_id", "times_reinforced"}.
    """
    if merchant_key is None:
        if not description:
            return {"error": "record_correction needs a merchant_key or a description"}
        normalizer = normalizer or await build_normalizer(conn)
        merchant_key = normalizer.normalize(description).key
    if not merchant_key:
        return {"error": "could not derive a merchant_key"}

    # Ensure the merchant directory has a row (FK-free, but keeps kNN/UI consistent).
    await conn.execute(
        "INSERT INTO finance.merchants (merchant_key, display_name) VALUES ($1, $2) "
        "ON CONFLICT (merchant_key) DO NOTHING",
        merchant_key, merchant_key.title(),
    )

    row = await conn.fetchrow(
        """
        INSERT INTO finance.merchant_memory (merchant_key, category_id, times_reinforced, last_reinforced_at)
        VALUES ($1, $2, 1, now())
        ON CONFLICT (merchant_key, category_id) DO UPDATE
            SET times_reinforced = finance.merchant_memory.times_reinforced + 1,
                last_reinforced_at = now()
        RETURNING times_reinforced
        """,
        merchant_key, category_id,
    )

    await conn.execute(
        """
        INSERT INTO finance.categorization_decision
            (transaction_id, tier, confidence, applied_category_id, auto_applied, rationale)
        VALUES ($1, 'correction', 1.0, $2, false, $3::jsonb)
        """,
        transaction_id or f"merchant:{merchant_key}", category_id,
        {"source": source, "merchant_key": merchant_key},
    )

    logger.info("LearningService: reinforced %s → category %s (source=%s)",
                merchant_key, category_id, source)
    return {
        "merchant_key": merchant_key,
        "category_id": category_id,
        "times_reinforced": row["times_reinforced"],
    }
