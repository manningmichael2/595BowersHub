"""RuleEngine — tier 1 (R2.1). Deterministic user rules, first-match-wins.

Evaluates `finance.user_rules` in user-orderable `priority` order. A rule matches
when EVERY specified (non-null) condition matches — any combination of
`merchant_key`, raw-description regex, amount range (`amount_min`/`amount_max`),
and `account_id`. The first matching rule emits `Decision(confidence=1.0,
terminal=True)` — rule-locked, never overwritten by later tiers (R3.4). Replaces
the fuzzy `similarity()>0.20` ILIKE hack.

`apply_rule_to_existing` re-runs a rule's predicate over history on demand
(R2.1/R3.3) — the bulk write itself goes through the Writer choke point with RBAC
in Task 11; this provides the predicate + a guarded direct apply for the service.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import List, Optional

from .base import Decision, TxnContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserRule:
    id: int
    priority: int
    category_id: int
    merchant_key: Optional[str] = None
    description_regex: Optional[str] = None
    amount_min: Optional[float] = None
    amount_max: Optional[float] = None
    account_id: Optional[str] = None

    def has_conditions(self) -> bool:
        """A rule with no conditions would match everything — treat as inert."""
        return any(c is not None for c in (
            self.merchant_key, self.description_regex, self.amount_min,
            self.amount_max, self.account_id))

    def matches(self, ctx: TxnContext) -> bool:
        if not self.has_conditions():
            return False
        if self.merchant_key is not None and ctx.merchant_key != self.merchant_key:
            return False
        if self.account_id is not None and ctx.account_id != self.account_id:
            return False
        if self.amount_min is not None and ctx.amount < self.amount_min:
            return False
        if self.amount_max is not None and ctx.amount > self.amount_max:
            return False
        if self.description_regex is not None:
            try:
                if not re.search(self.description_regex, ctx.description or "", re.IGNORECASE):
                    return False
            except re.error:
                logger.warning("user_rule %s has an invalid regex; skipping", self.id)
                return False
        return True


class RuleEngine:
    tier = "rule"

    def __init__(self, rules: List[UserRule]):
        # Pre-sorted: priority asc, then id asc (stable first-match-wins).
        self._rules = sorted(rules, key=lambda r: (r.priority, r.id))

    async def classify(self, ctx: TxnContext) -> Decision:
        for rule in self._rules:
            if rule.matches(ctx):
                return Decision(
                    category_id=rule.category_id, confidence=1.0, tier=self.tier,
                    terminal=True,
                    rationale={"rule_id": rule.id, "priority": rule.priority},
                )
        return Decision.abstain(self.tier)


async def load_rules(conn) -> List[UserRule]:
    rows = await conn.fetch(
        "SELECT id, priority, category_id, merchant_key, description_regex, "
        "amount_min, amount_max, account_id FROM finance.user_rules "
        "WHERE is_active ORDER BY priority, id"
    )
    return [
        UserRule(
            id=r["id"], priority=r["priority"], category_id=r["category_id"],
            merchant_key=r["merchant_key"], description_regex=r["description_regex"],
            amount_min=float(r["amount_min"]) if r["amount_min"] is not None else None,
            amount_max=float(r["amount_max"]) if r["amount_max"] is not None else None,
            account_id=r["account_id"],
        )
        for r in rows
    ]


async def build_rule_engine(conn) -> RuleEngine:
    return RuleEngine(await load_rules(conn))


async def apply_rule_to_existing(conn, rule_id: int) -> dict:
    """Re-run one rule's predicate over history (R2.1/R3.3). Guarded so a manual
    override is never clobbered. Returns {"matched": n, "updated": m}.

    Bulk re-categorization via the API goes through the Writer choke point with
    provenance + RBAC (Task 11); this is the deterministic predicate apply the
    service layer calls."""
    row = await conn.fetchrow(
        "SELECT id, priority, category_id, merchant_key, description_regex, "
        "amount_min, amount_max, account_id FROM finance.user_rules WHERE id = $1",
        rule_id,
    )
    if not row:
        return {"matched": 0, "updated": 0, "error": "rule not found"}

    rule = UserRule(
        id=row["id"], priority=row["priority"], category_id=row["category_id"],
        merchant_key=row["merchant_key"], description_regex=row["description_regex"],
        amount_min=float(row["amount_min"]) if row["amount_min"] is not None else None,
        amount_max=float(row["amount_max"]) if row["amount_max"] is not None else None,
        account_id=row["account_id"],
    )
    if not rule.has_conditions():
        return {"matched": 0, "updated": 0, "error": "rule has no conditions"}

    # Fetch all non-transfer rows so `matched` reflects the predicate itself; the
    # guarded UPDATE below is what skips manual overrides (so the guard's effect
    # is observable as matched > updated).
    txns = await conn.fetch(
        "SELECT id, description, amount, account_id, merchant_key "
        "FROM finance.transactions WHERE is_transfer = false"
    )
    matched = 0
    updated = 0
    for t in txns:
        ctx = TxnContext(
            txn_id=t["id"], description=t["description"] or "", amount=float(t["amount"]),
            account_id=t["account_id"], merchant_key=t["merchant_key"],
        )
        if not rule.matches(ctx):
            continue
        matched += 1
        result = await conn.execute(
            "UPDATE finance.transactions SET category_id = $1, categorized_by_tier = 'rule', "
            "categorization_confidence = 1.0, updated_at = now() "
            "WHERE id = $2 AND user_category_override = false",
            rule.category_id, t["id"],
        )
        if result.endswith(" 1"):
            updated += 1
    return {"matched": matched, "updated": updated}
