"""Evaluation harness for the categorization cascade (R2.7).

Scores a classifier against the hand-verified `finance.eval_labels` set, so the
model choice (R2.4) and per-tier thresholds (R2.5) are empirical, not asserted.
Doubles as a CI regression guard whenever the `categorizer` role or thresholds
change (wired in Task 13).

This module is the *plumbing*: it takes any async classifier callable
(`(TxnContext) -> Decision`) and reports per-tier / per-model accuracy plus a
transfer-flag confusion matrix. Full-cascade scoring (running the real pipeline
over the labels) is wired once all tiers exist (Task 13) — the harness itself is
classifier-agnostic so a stub, a single tier, or the whole cascade all score the
same way.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional

from .categorization.base import Decision, TxnContext

logger = logging.getLogger(__name__)

# An async classifier: given a transaction context, return a Decision.
Classify = Callable[[TxnContext], Awaitable[Decision]]


@dataclass
class EvalLabel:
    """One hand-verified expectation from finance.eval_labels."""

    id: int
    description: str
    account_type: Optional[str]
    amount: Optional[float]
    expected_category_id: Optional[int]
    is_transfer_expected: bool
    notes: Optional[str] = None

    def to_context(self) -> TxnContext:
        """Build the classifier input from this label. The eval set carries no
        real account id / merchant_key — tiers that need those (rules by
        account, kNN) abstain on eval rows, which is the correct behavior to
        measure (we score what each tier *can* decide from a descriptor)."""
        return TxnContext(
            txn_id=f"eval:{self.id}",
            description=self.description,
            amount=float(self.amount) if self.amount is not None else 0.0,
            account_type=self.account_type,
        )


@dataclass
class TierStat:
    n: int = 0
    correct: int = 0

    @property
    def accuracy(self) -> float:
        return self.correct / self.n if self.n else 0.0


@dataclass
class ConfusionMatrix:
    """Transfer-flag confusion (positive = "is a transfer")."""

    tp: int = 0
    fp: int = 0
    tn: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom else 0.0


@dataclass
class EvalReport:
    total: int = 0
    correct: int = 0
    abstained: int = 0
    per_tier: dict[str, TierStat] = field(default_factory=dict)
    per_model: dict[str, TierStat] = field(default_factory=dict)
    transfer: ConfusionMatrix = field(default_factory=ConfusionMatrix)

    @property
    def accuracy(self) -> float:
        """Category accuracy over non-transfer labels that were decided."""
        return self.correct / self.total if self.total else 0.0

    def as_dict(self) -> dict:
        return {
            "total": self.total,
            "correct": self.correct,
            "abstained": self.abstained,
            "accuracy": round(self.accuracy, 4),
            "per_tier": {
                k: {"n": v.n, "correct": v.correct, "accuracy": round(v.accuracy, 4)}
                for k, v in sorted(self.per_tier.items())
            },
            "per_model": {
                k: {"n": v.n, "correct": v.correct, "accuracy": round(v.accuracy, 4)}
                for k, v in sorted(self.per_model.items())
            },
            "transfer": {
                "tp": self.transfer.tp, "fp": self.transfer.fp,
                "tn": self.transfer.tn, "fn": self.transfer.fn,
                "precision": round(self.transfer.precision, 4),
                "recall": round(self.transfer.recall, 4),
            },
        }


async def score_cascade(pool, *, embeddings_client=None, llm_call_model=None,
                        config=None) -> EvalReport:
    """Full-cascade scoring (R2.7, deferred from Task 4 — now that the tiers +
    pipeline exist). Runs the REAL pipeline over each eval label and scores the
    decision the cascade would *auto-apply* (sub-threshold guesses count as
    abstains, transfer flags are scored regardless of the gate).

    `embeddings_client` / `llm_call_model` are injectable so CI can score the
    deterministic tiers without a live Ollama; the live model A/B (per-`categorizer`
    role) passes the real clients. See docs/finance-categorization-cutover.md.
    """
    # Imported here to avoid a circular import (pipeline imports base only).
    from .categorization.config import load_config
    from .categorization.knn import EmbeddingKNN
    from .categorization.llm import build_llm_tier
    from .categorization.memory import MerchantMemory
    from .categorization.pipeline import CategorizationPipeline
    from .categorization.rules import build_rule_engine
    from .categorization.transfer import TransferDetector
    from .embeddings import EmbeddingsClient
    from .merchant_normalizer import build_normalizer

    client = embeddings_client or EmbeddingsClient("http://ollama:11434", pool)
    async with pool.acquire() as conn:
        if config is None:
            config = await load_config(conn)
        labels = await load_eval_labels(conn)
        normalizer = await build_normalizer(conn)
        knn = config.knn
        tiers = [
            TransferDetector(conn),
            await build_rule_engine(conn),
            MerchantMemory(conn),
            EmbeddingKNN(conn, client, k=int(knn.get("k", 15)),
                         min_neighbors=int(knn.get("min_neighbors", 3))),
            await build_llm_tier(conn, call_model=llm_call_model),
        ]
        pipeline = CategorizationPipeline(tiers, config)

        async def classify(ctx: TxnContext) -> Decision:
            ctx.merchant_key = normalizer.normalize(ctx.description).key
            result = await pipeline.classify(ctx)
            d = result.decision
            if result.auto_apply or d.is_transfer:
                return d
            # Sub-threshold guess → queued, not applied → counts as an abstain.
            return Decision(category_id=None, confidence=d.confidence, tier=d.tier,
                            is_transfer=d.is_transfer, rationale=d.rationale)

        return await score_classifier(classify, labels)


async def write_thresholds(conn, thresholds: dict) -> None:
    """Persist calibrated per-tier τ to finance.categorizer_config (R2.5)."""
    await conn.execute(
        "INSERT INTO finance.categorizer_config (key, value, updated_at) "
        "VALUES ('thresholds', $1::jsonb, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        thresholds,
    )


async def set_engine(conn, engine: str) -> None:
    """Flip the categorizer_engine gate (legacy|shadow|cascade)."""
    from .categorization.config import VALID_ENGINES
    if engine not in VALID_ENGINES:
        raise ValueError(f"invalid engine {engine!r}")
    # The jsonb codec passes str through as-is (assumes pre-serialized JSON), so a
    # bare "shadow" is invalid JSON — encode it to a quoted JSON string.
    await conn.execute(
        "INSERT INTO finance.categorizer_config (key, value, updated_at) "
        "VALUES ('categorizer_engine', $1::jsonb, now()) "
        "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        json.dumps(engine),
    )


async def load_eval_labels(conn) -> List[EvalLabel]:
    rows = await conn.fetch(
        "SELECT id, description, account_type, amount, expected_category_id, "
        "is_transfer_expected, notes FROM finance.eval_labels ORDER BY id"
    )
    return [
        EvalLabel(
            id=r["id"],
            description=r["description"],
            account_type=r["account_type"],
            amount=float(r["amount"]) if r["amount"] is not None else None,
            expected_category_id=r["expected_category_id"],
            is_transfer_expected=r["is_transfer_expected"],
            notes=r["notes"],
        )
        for r in rows
    ]


async def score_classifier(classify: Classify, labels: List[EvalLabel]) -> EvalReport:
    """Run `classify` over every label and tally accuracy + transfer confusion.

    Category accuracy is measured only over the non-transfer labels (a transfer
    has no spending category); transfer detection is scored separately via the
    confusion matrix so a tier that correctly flags a transfer is not penalized
    for "missing" a spending category that should not exist.
    """
    report = EvalReport()
    for label in labels:
        decision = await classify(label.to_context())

        # Transfer-flag confusion (every label participates).
        predicted_transfer = decision.is_transfer
        if label.is_transfer_expected and predicted_transfer:
            report.transfer.tp += 1
        elif label.is_transfer_expected and not predicted_transfer:
            report.transfer.fn += 1
        elif not label.is_transfer_expected and predicted_transfer:
            report.transfer.fp += 1
        else:
            report.transfer.tn += 1

        # Category accuracy: skip transfer-expected labels (no spending category).
        if label.is_transfer_expected:
            continue
        report.total += 1

        if decision.category_id is None:
            report.abstained += 1
            continue

        is_correct = decision.category_id == label.expected_category_id
        if is_correct:
            report.correct += 1

        tier_stat = report.per_tier.setdefault(decision.tier, TierStat())
        tier_stat.n += 1
        tier_stat.correct += int(is_correct)

        model_id = (decision.rationale or {}).get("model_id")
        if model_id:
            model_stat = report.per_model.setdefault(model_id, TierStat())
            model_stat.n += 1
            model_stat.correct += int(is_correct)

    return report
