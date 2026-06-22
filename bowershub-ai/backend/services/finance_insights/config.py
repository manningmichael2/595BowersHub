"""DB-driven insight config loader (R2.2).

`finance.insight_config` (key → jsonb) is the source of truth for every detector
enable flag, threshold, the global kill-switch, and the retirement keyword set
(seeded idempotently by migration 0035). Code holds the same values ONLY as a
missing-key fallback, so a fresh row or an operator edit always wins and nothing
is hardcoded at a call site.
"""

from __future__ import annotations

from typing import Any, Dict

# Missing-key fallback ONLY (the DB seed in 0035 is the real source). Kept in sync
# with that migration; if a key is absent from the DB, these keep the agent
# functioning rather than KeyError-ing at 3am.
_DEFAULTS: Dict[str, Any] = {
    "insights_enabled": True,
    "insights_cooldown_days": 7,
    "detector.duplicate_charge.enabled": True,
    "detector.duplicate_charge.window_days": 3,
    "detector.duplicate_charge.amount_tolerance": 0.0,
    "detector.price_creep.enabled": True,
    "detector.price_creep.min_increase_pct": 0.15,
    "detector.price_creep.min_history": 3,
    "detector.free_trial_conversion.enabled": True,
    "detector.free_trial_conversion.min_amount": 5.0,
    "detector.free_trial_conversion.lookback_days": 45,
    "detector.unusual_spend.enabled": True,
    "detector.unusual_spend.mad_multiplier": 3.0,
    "detector.unusual_spend.min_history": 6,
    "detector.bill_higher_than_usual.enabled": True,
    "detector.bill_higher_than_usual.iqr_multiplier": 1.5,
    "detector.bill_higher_than_usual.min_history": 4,
    "detector.low_balance_before_payday.enabled": True,
    "detector.low_balance_before_payday.floor": 100.0,
    "retirement_keywords": [
        "retire", "retirement", "fire", "nest egg", "withdraw", "withdrawal",
        "coast", "pension", "401k", "ira", "roth", "social security",
    ],
}


class InsightConfig:
    """Read-only view over the merged (DB-over-defaults) config."""

    def __init__(self, values: Dict[str, Any]):
        self._values = values

    def get(self, key: str, default: Any = None) -> Any:
        if key in self._values:
            return self._values[key]
        if key in _DEFAULTS:
            return _DEFAULTS[key]
        return default

    def enabled(self, detector: str) -> bool:
        return bool(self.get(f"detector.{detector}.enabled", True))

    @property
    def insights_enabled(self) -> bool:
        return bool(self.get("insights_enabled", True))

    @property
    def retirement_keywords(self) -> list[str]:
        return list(self.get("retirement_keywords", []))


async def load_insight_config(conn) -> InsightConfig:
    """Load finance.insight_config, layering DB rows over the code defaults."""
    merged: Dict[str, Any] = dict(_DEFAULTS)
    try:
        rows = await conn.fetch("SELECT key, value FROM finance.insight_config")
    except Exception:
        # Table missing (pre-migration) → defaults only; never raise.
        return InsightConfig(merged)
    for r in rows:
        merged[r["key"]] = r["value"]
    return InsightConfig(merged)
