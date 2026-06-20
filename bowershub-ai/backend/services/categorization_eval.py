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
