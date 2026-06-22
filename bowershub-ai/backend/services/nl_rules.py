"""Natural-language → categorization rule (R3.1, R3.2, R3.3, R3.4).

`propose_rule_candidate` turns free text ("always categorize Whole Foods as
Groceries unless over $200") into a structured candidate via the governed
`FinanceNarrator.propose_structured` boundary (constrained tool-use, never a
write). `validate_rule_candidate` is the SECURITY CONTROL (R3.4): the category
must exist, the merchant must resolve to a REAL merchant_key, bounds/priority are
clamped, and an unbounded-scope candidate (one that would match everything) is
rejected. The model proposes; validation gates; commit is the existing
require_admin POST /user-rules.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from backend.services.categorization.rules import UserRule
from backend.services.finance_narration import FinanceNarrator

# Tool-use schema for the constrained candidate (no free-form SQL/writes).
RULE_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string", "description": "The merchant the rule targets."},
        "category": {"type": "string", "description": "The category NAME to assign."},
        "amount_min": {"type": ["number", "null"], "description": "Min signed amount, or null."},
        "amount_max": {"type": ["number", "null"], "description": "Max signed amount, or null."},
        "priority": {"type": ["integer", "null"], "description": "Rule priority, or null."},
    },
    "required": ["merchant", "category"],
}

_PRIORITY_MIN, _PRIORITY_MAX, _PRIORITY_DEFAULT = 1, 1000, 100


class RuleValidationError(ValueError):
    """Raised when a proposed candidate fails the security/validity gate."""


class ValidatedRule:
    """A validated, ready-to-commit rule candidate + display context."""

    def __init__(self, *, category_id: int, category_name: str, merchant_key: str,
                 amount_min: Optional[float], amount_max: Optional[float], priority: int):
        self.category_id = category_id
        self.category_name = category_name
        self.merchant_key = merchant_key
        self.amount_min = amount_min
        self.amount_max = amount_max
        self.priority = priority

    def to_user_rule(self) -> UserRule:
        return UserRule(
            id=0, priority=self.priority, category_id=self.category_id,
            merchant_key=self.merchant_key, amount_min=self.amount_min,
            amount_max=self.amount_max,
        )

    def to_commit_payload(self) -> dict:
        return {
            "priority": self.priority, "category_id": self.category_id,
            "merchant_key": self.merchant_key, "description_regex": None,
            "amount_min": self.amount_min, "amount_max": self.amount_max,
            "account_id": None, "is_active": True,
        }


async def propose_rule_candidate(provider, nl_text: str) -> dict:
    """Constrained NL → candidate via the narration boundary (never a write)."""
    return await FinanceNarrator(provider).propose_structured(RULE_SCHEMA, nl_text)


def _num(v: Any) -> Optional[float]:
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        raise RuleValidationError(f"invalid amount: {v!r}")


async def _resolve_category(conn, name: Any) -> tuple[int, str]:
    n = (str(name) if name is not None else "").strip()
    if not n:
        raise RuleValidationError("category is required")
    row = await conn.fetchrow(
        "SELECT id, name FROM finance.categories WHERE lower(name) = lower($1)", n
    )
    if row:
        return row["id"], row["name"]
    rows = await conn.fetch("SELECT id, name FROM finance.categories WHERE name ILIKE $1", f"%{n}%")
    if len(rows) == 1:
        return rows[0]["id"], rows[0]["name"]
    raise RuleValidationError(f"unknown category {n!r}")


async def _resolve_merchant(conn, name: Any) -> str:
    n = (str(name) if name is not None else "").strip()
    if not n:
        raise RuleValidationError("merchant is required (an unbounded rule is rejected)")
    row = await conn.fetchrow(
        "SELECT merchant_key FROM finance.transactions "
        "WHERE lower(merchant_key) = lower($1) LIMIT 1", n
    )
    if row:
        return row["merchant_key"]
    rows = await conn.fetch(
        "SELECT DISTINCT merchant_key FROM finance.transactions "
        "WHERE merchant_key ILIKE $1 AND merchant_key IS NOT NULL LIMIT 2", f"%{n}%"
    )
    if len(rows) == 1:
        return rows[0]["merchant_key"]
    raise RuleValidationError(f"merchant {n!r} does not resolve to a known merchant")


async def validate_rule_candidate(conn, raw: dict) -> ValidatedRule:
    """The security control (R3.4). Reject anything that doesn't resolve to a real
    category + merchant, clamp bounds/priority, and never allow an unbounded rule."""
    if not isinstance(raw, dict):
        raise RuleValidationError("candidate is not an object")

    category_id, category_name = await _resolve_category(conn, raw.get("category"))
    merchant_key = await _resolve_merchant(conn, raw.get("merchant"))

    amount_min = _num(raw.get("amount_min"))
    amount_max = _num(raw.get("amount_max"))
    if amount_min is not None and amount_max is not None and amount_min > amount_max:
        amount_min, amount_max = amount_max, amount_min

    priority = raw.get("priority")
    try:
        priority = _PRIORITY_DEFAULT if priority in (None, "") else int(priority)
    except (TypeError, ValueError):
        priority = _PRIORITY_DEFAULT
    priority = max(_PRIORITY_MIN, min(_PRIORITY_MAX, priority))

    validated = ValidatedRule(
        category_id=category_id, category_name=category_name, merchant_key=merchant_key,
        amount_min=amount_min, amount_max=amount_max, priority=priority,
    )
    # Belt-and-suspenders: a rule with no conditions matches everything — never commit it.
    if not validated.to_user_rule().has_conditions():
        raise RuleValidationError("rule has no conditions (would match every transaction)")
    return validated
