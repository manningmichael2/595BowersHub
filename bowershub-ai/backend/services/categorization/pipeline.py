"""CategorizationPipeline + ConfidenceGate + Writer (R2.5/R2.6/R3.4/R5.1-3).

The pipeline runs tiers in **fixed code order** (transfer→rule→memory→kNN→LLM,
R5.3), short-circuits on the first decision that clears its per-tier threshold or
on `is_transfer`/`terminal` (R2.6), and otherwise returns the best sub-threshold
decision so the queue can show "we guessed X at 0.4" (R4.1).

The ConfidenceGate compares a decision against the per-tier threshold from
finance.categorizer_config (R2.5) — confidence is gated per tier, not by one
global threshold (critic M5).

The Writer is the one choke point (R5.1): schema-qualified, write-time re-check of
`user_category_override=false AND category_id IS NULL` (R3.4), per-row commit
(idempotent/resumable, R5.2), and an append-only provenance row with
`prior_category_id` so any auto-write is reversible (R2.6). In shadow mode it
mutates NOTHING — category *and* is_transfer — and only logs (critic M4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional

from .base import Classifier, Decision, TxnContext
from .config import CategorizerConfig

logger = logging.getLogger(__name__)


class ConfidenceGate:
    """Per-tier auto-apply gate (R2.5)."""

    def __init__(self, config: CategorizerConfig):
        self._config = config

    def clears(self, decision: Decision) -> bool:
        if decision.category_id is None and not decision.is_transfer:
            return False
        return decision.confidence >= self._config.threshold(decision.tier)


@dataclass
class PipelineResult:
    decision: Decision     # chosen decision (may be an abstain)
    auto_apply: bool       # cleared its per-tier gate (intent; Writer suppresses in shadow)

    @property
    def is_actionable(self) -> bool:
        """Worth a provenance row: a prediction or a transfer flag (not pure abstain)."""
        return self.decision.category_id is not None or self.decision.is_transfer


class CategorizationPipeline:
    def __init__(self, tiers: List[Classifier], config: CategorizerConfig):
        self._tiers = tiers
        self._config = config
        self._gate = ConfidenceGate(config)

    async def classify(self, ctx: TxnContext) -> PipelineResult:
        best: Optional[Decision] = None  # best sub-threshold candidate for the queue
        for tier in self._tiers:
            if not self._config.is_enabled(tier.tier):
                continue
            decision = await tier.classify(ctx)

            # Transfer axis short-circuits regardless of confidence (R6.4); the gate
            # decides auto-flag (>= τ_transfer) vs "transfer?" queue.
            if decision.is_transfer:
                return PipelineResult(decision=decision, auto_apply=self._gate.clears(decision))

            if decision.category_id is None:
                continue  # abstain → next tier

            # Terminal (rule/transfer lock) short-circuits and is never re-evaluated.
            if decision.terminal:
                return PipelineResult(decision=decision, auto_apply=self._gate.clears(decision))

            if self._gate.clears(decision):
                return PipelineResult(decision=decision, auto_apply=True)

            # Sub-threshold candidate — keep the most confident for the queue.
            if best is None or decision.confidence > best.confidence:
                best = decision

        if best is not None:
            return PipelineResult(decision=best, auto_apply=False)
        return PipelineResult(decision=Decision.abstain("none"), auto_apply=False)


class Writer:
    """The single category/transfer write choke point."""

    async def apply(self, conn, ctx: TxnContext, result: PipelineResult, *,
                    shadow: bool, prior_category_id: Optional[int] = None) -> dict:
        decision = result.decision
        wrote_category = False
        wrote_transfer = False

        if not shadow and result.auto_apply:
            if decision.is_transfer:
                res = await conn.execute(
                    "UPDATE finance.transactions SET is_transfer = true, updated_at = now() "
                    "WHERE id = $1 AND is_transfer = false AND is_transfer_manual = false",
                    ctx.txn_id,
                )
                wrote_transfer = res.endswith(" 1")
            elif decision.category_id is not None:
                # Write-time re-check (R3.4) + idempotent guard (R5.2).
                res = await conn.execute(
                    "UPDATE finance.transactions "
                    "SET category_id = $1, categorized_by_tier = $2, "
                    "    categorization_confidence = $3, updated_at = now() "
                    "WHERE id = $4 AND user_category_override = false AND category_id IS NULL "
                    "  AND is_split = false",  # never categorize a split parent (R1.5 defense-in-depth)
                    decision.category_id, decision.tier, decision.confidence, ctx.txn_id,
                )
                wrote_category = res.endswith(" 1")

        if result.is_actionable:
            await conn.execute(
                """
                INSERT INTO finance.categorization_decision
                    (transaction_id, tier, confidence, model_id, prior_category_id,
                     applied_category_id, is_transfer_set, auto_applied, rationale)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)
                """,
                ctx.txn_id, decision.tier, decision.confidence,
                (decision.rationale or {}).get("model_id"),
                prior_category_id, decision.category_id,
                decision.is_transfer, (wrote_category or wrote_transfer),
                decision.rationale or {},
            )

        return {"wrote_category": wrote_category, "wrote_transfer": wrote_transfer}
