"""Core value objects for the categorization cascade — the spine of R2.5/R2.6.

`Decision` is what every tier returns; its uniformity is what makes one DB
threshold meaningful across tiers and keeps the pipeline tier-agnostic.
`TxnContext` is the per-transaction input, pre-fetched once and passed to every
tier (not re-queried per tier).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional, Protocol, runtime_checkable


@dataclass(frozen=True)
class Decision:
    """The uniform result every tier returns.

    `category_id is None` ⇒ abstain → the cascade continues. A non-null decision
    is gated by `ConfidenceGate`. The pipeline NEVER produces "Other" — a
    sub-threshold decision goes to the review queue, not a fallback category.
    """

    category_id: Optional[int]      # None = abstain → cascade continues
    confidence: float               # common [0,1] scale (R2.5)
    tier: str                       # 'transfer'|'rule'|'merchant_memory'|'embedding_knn'|'llm'
    rationale: dict = field(default_factory=dict)  # evidence for R4.1
    is_transfer: bool = False       # R6 short-circuit
    terminal: bool = False          # rule/transfer lock — never re-evaluated (R3.4/R6.4)

    @classmethod
    def abstain(cls, tier: str, *, rationale: Optional[dict] = None) -> "Decision":
        """Convenience: a tier declines to decide (no category, zero confidence)."""
        return cls(category_id=None, confidence=0.0, tier=tier, rationale=rationale or {})


@dataclass
class TxnContext:
    """Everything a tier needs about one transaction, fetched once per row.

    `merchant_key` may be None for rows ingested before the normalization hook
    shipped; the pipeline derives it inline-on-read (B3) so tiers 1–3 never
    silently miss.
    """

    txn_id: str
    description: str
    amount: float
    account_id: Optional[str] = None
    account_type: Optional[str] = None       # checking|savings|credit_card|loan|mortgage|brokerage (R6.2)
    merchant_key: Optional[str] = None
    posted_date: Optional[date] = None
    memo: Optional[str] = None
    is_transfer_manual: bool = False


@runtime_checkable
class Classifier(Protocol):
    """Tier protocol — mirrors the injectable DiscoverySource pattern so tiers
    are fakeable in tests. Each tier declares its `tier` name and implements an
    async `classify(ctx) -> Decision`."""

    tier: str

    async def classify(self, ctx: TxnContext) -> Decision: ...
