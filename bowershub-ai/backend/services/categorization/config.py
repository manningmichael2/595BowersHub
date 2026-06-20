"""DB-driven categorizer config (R2.5) — loaded from finance.categorizer_config.

All operational knobs are rows, not constants (NO-HARDCODING): the rollout
feature-gate, per-tier auto-apply thresholds, per-tier enable flags, kNN sizing,
and recurring-charge tolerances. Defaults are seeded in 0023; this loader applies
the same defaults in code so a missing key never crashes a tier.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Mirrors the 0023 seed. Code-side defaults so a missing row degrades gracefully.
_DEFAULT_THRESHOLDS = {"rule": 1.0, "merchant_memory": 0.8, "embedding_knn": 0.7, "llm": 0.6, "transfer": 0.9}
_DEFAULT_TIERS_ENABLED = {"transfer": True, "rule": True, "merchant_memory": True, "embedding_knn": True, "llm": True}
_DEFAULT_KNN = {"k": 15, "min_neighbors": 3}
_DEFAULT_RECURRING = {"min_occurrences": 3, "amount_tolerance_pct": 15, "interval_tolerance_days": 4}

VALID_ENGINES = frozenset({"legacy", "shadow", "cascade"})


@dataclass(frozen=True)
class CategorizerConfig:
    engine: str = "legacy"
    thresholds: dict = field(default_factory=lambda: dict(_DEFAULT_THRESHOLDS))
    tiers_enabled: dict = field(default_factory=lambda: dict(_DEFAULT_TIERS_ENABLED))
    knn: dict = field(default_factory=lambda: dict(_DEFAULT_KNN))
    recurring: dict = field(default_factory=lambda: dict(_DEFAULT_RECURRING))

    def threshold(self, tier: str) -> float:
        return float(self.thresholds.get(tier, _DEFAULT_THRESHOLDS.get(tier, 0.7)))

    def is_enabled(self, tier: str) -> bool:
        return bool(self.tiers_enabled.get(tier, True))


def _as_dict(value: Any, default: dict) -> dict:
    if isinstance(value, dict):
        merged = dict(default)
        merged.update(value)
        return merged
    return dict(default)


async def load_config(conn) -> CategorizerConfig:
    """Load the full config from finance.categorizer_config, applying defaults for
    any missing key."""
    rows = await conn.fetch("SELECT key, value FROM finance.categorizer_config")
    raw = {r["key"]: r["value"] for r in rows}

    engine = raw.get("categorizer_engine")
    if isinstance(engine, str):
        engine = engine.strip().strip('"')
    if engine not in VALID_ENGINES:
        engine = "legacy"

    return CategorizerConfig(
        engine=engine,
        thresholds=_as_dict(raw.get("thresholds"), _DEFAULT_THRESHOLDS),
        tiers_enabled=_as_dict(raw.get("tiers_enabled"), _DEFAULT_TIERS_ENABLED),
        knn=_as_dict(raw.get("knn"), _DEFAULT_KNN),
        recurring=_as_dict(raw.get("recurring"), _DEFAULT_RECURRING),
    )
