"""MerchantMemory — tier 2 (R2.2/R3.2), the deterministic learned tier.

For a `merchant_key`, consults (a) the directory `category_prior_id` on
finance.merchants (R1.2 — e.g. an MCC-derived cold-start prior) and (b) the
strongest learned signal in finance.merchant_memory. **Consulted before any model
call** (R2.2) — so a corrected merchant is re-categorized with zero LLM cost next
time (the "correction stickiness" success metric). Confidence is a bounded
monotone function of reinforcement count + recency.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Optional

from .base import Decision, TxnContext

logger = logging.getLogger(__name__)

# Reinforcement → base confidence: 1 correction → 0.70, then +0.05 each, capped.
_BASE_FLOOR = 0.70
_BASE_STEP = 0.05
_BASE_CAP = 0.95
# Recency half-life (days) for the gentle decay applied to the base confidence.
_HALF_LIFE_DAYS = 730.0
# A bare directory prior (no learned reinforcement) is a weaker signal.
_PRIOR_CONFIDENCE = 0.65


def memory_confidence(times_reinforced: int, last_reinforced_at: Optional[datetime],
                      *, now: Optional[datetime] = None) -> float:
    """Bounded monotone confidence: rises with reinforcement, gently decays with age."""
    base = min(_BASE_CAP, _BASE_FLOOR + _BASE_STEP * max(0, times_reinforced - 1))
    if last_reinforced_at is None:
        return base
    now = now or datetime.now(timezone.utc)
    last = last_reinforced_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    days = max(0.0, (now - last).total_seconds() / 86400.0)
    decay = math.pow(0.5, days / _HALF_LIFE_DAYS)        # 1.0 → 0.5 over a half-life
    # Recency moves confidence within [0.85, 1.0] of base (never zeroes a strong signal).
    return round(base * (0.85 + 0.15 * decay), 4)


class MerchantMemory:
    tier = "merchant_memory"

    def __init__(self, conn):
        self._conn = conn

    async def classify(self, ctx: TxnContext) -> Decision:
        if not ctx.merchant_key:
            return Decision.abstain(self.tier)

        learned = await self._conn.fetchrow(
            "SELECT category_id, times_reinforced, last_reinforced_at "
            "FROM finance.merchant_memory WHERE merchant_key = $1 "
            "ORDER BY times_reinforced DESC, last_reinforced_at DESC LIMIT 1",
            ctx.merchant_key,
        )
        if learned:
            conf = memory_confidence(learned["times_reinforced"], learned["last_reinforced_at"])
            return Decision(
                category_id=learned["category_id"], confidence=conf, tier=self.tier,
                rationale={
                    "source": "merchant_memory",
                    "merchant_key": ctx.merchant_key,
                    "times_reinforced": learned["times_reinforced"],
                },
            )

        prior = await self._conn.fetchval(
            "SELECT category_prior_id FROM finance.merchants WHERE merchant_key = $1",
            ctx.merchant_key,
        )
        if prior is not None:
            return Decision(
                category_id=prior, confidence=_PRIOR_CONFIDENCE, tier=self.tier,
                rationale={"source": "category_prior", "merchant_key": ctx.merchant_key},
            )

        return Decision.abstain(self.tier)
