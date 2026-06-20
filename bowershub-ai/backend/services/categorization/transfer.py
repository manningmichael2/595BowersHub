"""TransferDetector — tier 0 of the cascade (R6), runs first, conservative by design.

Flags inter-account transfers (R6.1) and liability-account payments (R6.2), sets
`is_transfer`, and short-circuits spending categorization (R6.4). Liability
detection uses the DB-driven `finance.accounts.account_type` — NOT hardcoded
merchant matching.

**Asymmetric gate (the key safety property):** auto-flag only on *high*
confidence — a counterpart-matched transfer or a confirmed payment into a known
liability. Everything ambiguous (single-leg descriptor heuristics) returns a
*low-confidence* transfer Decision, which the ConfidenceGate routes to a distinct
"transfer?" review item (R6.3) — never a silent flag. Rationale: a false transfer
flag silently removes real spending from every budget; a missed flag is one
manually-fixable queue item.

`is_transfer_manual` is honored in the predicate (M6): a hand-marked row is
excluded from auto-flagging entirely (the detector abstains and the owner's value
stands).
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from .base import Decision, TxnContext

logger = logging.getLogger(__name__)

# Liability account types — a payment INTO one of these is a debt paydown, not
# spending (R6.2). DB-driven via finance.accounts.account_type.
LIABILITY_TYPES = frozenset({"credit_card", "loan", "mortgage"})

# Confirmed-payment descriptor (turns a liability inflow into a high-confidence
# transfer). "THANK YOU" is the classic credit-card-payment confirmation line.
_PAYMENT_RE = re.compile(
    r"\b(PAYMENT|AUTOPAY|AUTO\s*PAY|PYMT|PMT|THANK\s*YOU|E-?PAYMENT|BILL\s*PAY|EPAY)\b",
    re.IGNORECASE,
)
# Single-leg transfer descriptors (ambiguous → "transfer?" queue, never auto).
# Note: bare "WITHDRAWAL" (e.g. ATM cash) is intentionally NOT here.
_TRANSFER_RE = re.compile(
    r"\b(TRANSFER|XFER|TFR|WIRE\s*TRANSFER|WITHDRAWAL\s+TO|DEPOSIT\s+FROM)\b",
    re.IGNORECASE,
)

# Confidence bands. >= τ_transfer (DB-configured, default 0.9) auto-flags; below
# routes to the "transfer?" queue.
_CONF_COUNTERPART = 0.98
_CONF_LIABILITY_CONFIRMED = 0.95
_CONF_AMBIGUOUS = 0.5


class TransferDetector:
    """Tier-0 transfer/debt detector. Needs a DB connection for counterpart
    matching (R6.1). Construct one per run with the active connection."""

    tier = "transfer"

    def __init__(self, conn, *, amount_tolerance: float = 0.01,
                 date_window_days: int = 4):
        self._conn = conn
        self._amount_tolerance = amount_tolerance
        self._date_window_days = date_window_days

    async def _find_counterpart(self, ctx: TxnContext) -> Optional[dict]:
        """Find an opposite-sign, ~equal-amount leg in a DIFFERENT own account
        within the date window (R6.1). Requires a real persisted row (account_id
        + posted_date); eval rows skip this path."""
        if not ctx.account_id or ctx.posted_date is None or ctx.amount == 0:
            return None
        row = await self._conn.fetchrow(
            """
            SELECT id, account_id, amount, posted_date
            FROM finance.transactions
            WHERE account_id <> $1
              AND id <> $2
              AND sign(amount) = -sign($3::numeric)
              AND abs(abs(amount) - abs($3::numeric)) <= $4
              AND abs(posted_date - $5::date) <= $6
            ORDER BY abs(posted_date - $5::date)
            LIMIT 1
            """,
            ctx.account_id, ctx.txn_id, ctx.amount,
            self._amount_tolerance, ctx.posted_date, self._date_window_days,
        )
        return dict(row) if row else None

    async def classify(self, ctx: TxnContext) -> Decision:
        # M6: a hand-marked row is excluded from auto-flagging entirely; the
        # owner's value stands. We abstain so the row flows on (the work-set
        # already excludes rows where is_transfer was manually set to true).
        if ctx.is_transfer_manual:
            return Decision.abstain(self.tier, rationale={"skipped": "is_transfer_manual"})

        desc = ctx.description or ""

        # 1. Counterpart-matched inter-account transfer (R6.1) — highest confidence.
        counterpart = await self._find_counterpart(ctx)
        if counterpart:
            return Decision(
                category_id=None, confidence=_CONF_COUNTERPART, tier=self.tier,
                is_transfer=True, terminal=True,
                rationale={
                    "method": "counterpart_match",
                    "counterpart_txn_id": counterpart["id"],
                    "counterpart_account_id": counterpart["account_id"],
                },
            )

        # 2. Payment into a known-liability account (R6.2). An inflow (amount > 0)
        #    that reduces a credit-card/loan/mortgage balance. Confirmed by a
        #    payment-like descriptor → auto; otherwise ambiguous (could be a
        #    refund) → "transfer?" queue.
        if ctx.account_type in LIABILITY_TYPES and ctx.amount > 0:
            if _PAYMENT_RE.search(desc):
                return Decision(
                    category_id=None, confidence=_CONF_LIABILITY_CONFIRMED, tier=self.tier,
                    is_transfer=True, terminal=True,
                    rationale={"method": "liability_payment", "account_type": ctx.account_type},
                )
            return Decision(
                category_id=None, confidence=_CONF_AMBIGUOUS, tier=self.tier,
                is_transfer=True, terminal=False,
                rationale={"method": "liability_inflow_unconfirmed", "account_type": ctx.account_type},
            )

        # 3. Single-leg descriptor heuristic (R6.3) — ambiguous → "transfer?" queue.
        if _TRANSFER_RE.search(desc) or _PAYMENT_RE.search(desc):
            return Decision(
                category_id=None, confidence=_CONF_AMBIGUOUS, tier=self.tier,
                is_transfer=True, terminal=False,
                rationale={"method": "descriptor_single_leg"},
            )

        return Decision.abstain(self.tier)
