"""DB-driven accounting config (R4.3) — loaded from finance.accounting_config.

Tunables are rows, not constants (NO-HARDCODING): transfer-match date window +
amount tolerance, reconcile tolerance, stale-balance window. Defaults are seeded
in 0030; these code-side defaults mean a missing key never crashes a caller.
Mirrors services/categorization/config.py.
"""

from __future__ import annotations

from dataclasses import dataclass

_DEFAULTS = {
    "match_date_window_days": 4,
    "match_amount_tolerance": 0.01,
    "reconcile_tolerance": 0.01,
    "stale_balance_days": 7,
}


@dataclass(frozen=True)
class AccountingConfig:
    match_date_window_days: int = _DEFAULTS["match_date_window_days"]
    match_amount_tolerance: float = _DEFAULTS["match_amount_tolerance"]
    reconcile_tolerance: float = _DEFAULTS["reconcile_tolerance"]
    stale_balance_days: int = _DEFAULTS["stale_balance_days"]


async def load_config(conn) -> AccountingConfig:
    """Load finance.accounting_config (jsonb scalar per key), applying defaults."""
    rows = await conn.fetch("SELECT key, value FROM finance.accounting_config")
    raw = {r["key"]: r["value"] for r in rows}
    return AccountingConfig(
        match_date_window_days=int(raw.get("match_date_window_days", _DEFAULTS["match_date_window_days"])),
        match_amount_tolerance=float(raw.get("match_amount_tolerance", _DEFAULTS["match_amount_tolerance"])),
        reconcile_tolerance=float(raw.get("reconcile_tolerance", _DEFAULTS["reconcile_tolerance"])),
        stale_balance_days=int(raw.get("stale_balance_days", _DEFAULTS["stale_balance_days"])),
    )
