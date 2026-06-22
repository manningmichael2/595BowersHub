"""Retirement service (R4.1, R4.3, R4.4, R4.6, R4.8).

Bridges the persisted, user-entered inputs (the singleton finance.retirement_inputs)
+ DB-driven assumption defaults (finance.retirement_config) to the pure projection
engine. Projections are REACTIVE: `project(overrides)` merges the live form
overrides over the saved inputs over the config defaults and recomputes WITHOUT
persisting, so the chart/stats update on every field change. Every projection
carries a non-nullable disclaimer (R4.6).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, List, Optional

from backend.services.accounting.networth import compute_net_worth
from backend.services.finance_projection import (
    Assumptions, RetirementInputs, project_series, retire_at_age,
)

DISCLAIMER = (
    "These projections are estimates based on the assumptions you entered — not "
    "guarantees. Real returns, inflation, and spending vary, and this is not "
    "financial advice."
)

# The fields a projection cannot run without (R4.8 cold-start otherwise).
_REQUIRED = ("current_age", "retirement_age", "current_balance",
             "annual_contribution", "annual_expenses")


class NeedsInputsError(Exception):
    """Raised when a projection is requested before the minimum inputs exist."""


class RetirementValidationError(ValueError):
    """Raised on an invalid age ordering or non-positive assumption."""


async def load_config(conn) -> Dict[str, float]:
    rows = await conn.fetch("SELECT key, value FROM finance.retirement_config")
    cfg = {r["key"]: r["value"] for r in rows}
    cfg.setdefault("nominal_return", 0.07)
    cfg.setdefault("inflation", 0.03)
    cfg.setdefault("withdrawal_rate", 0.04)
    cfg.setdefault("end_age", 95)
    return cfg


async def get_inputs(conn) -> Optional[Dict[str, Any]]:
    row = await conn.fetchrow("SELECT * FROM finance.retirement_inputs WHERE id = 1")
    return dict(row) if row else None


async def has_inputs(conn) -> bool:
    """R4.8: have the minimum inputs been entered? (a row with the required fields)."""
    row = await get_inputs(conn)
    return bool(row) and all(row.get(k) is not None for k in _REQUIRED)


async def prefill(conn) -> Dict[str, Any]:
    """Seed a fresh form: current_balance from net worth, assumptions from config,
    the rest blank for the user to fill (R4.1). Saved inputs win if present."""
    cfg = await load_config(conn)
    saved = await get_inputs(conn) or {}
    nw = await compute_net_worth(conn)
    return {
        "current_age": saved.get("current_age"),
        "retirement_age": saved.get("retirement_age"),
        "current_balance": _f(saved.get("current_balance")) if saved.get("current_balance") is not None
                           else float(nw.get("net_worth") or 0),
        "annual_salary": _f(saved.get("annual_salary")),
        "annual_contribution": _f(saved.get("annual_contribution")),
        "annual_expenses": _f(saved.get("annual_expenses")),
        "expected_return": _f(saved.get("expected_return")) if saved.get("expected_return") is not None
                           else float(cfg["nominal_return"]),
        "inflation": _f(saved.get("inflation_rate")) if saved.get("inflation_rate") is not None
                     else float(cfg["inflation"]),
        "withdrawal_rate": _f(saved.get("withdrawal_rate")) if saved.get("withdrawal_rate") is not None
                           else float(cfg["withdrawal_rate"]),
        "end_age": saved.get("end_age") if saved.get("end_age") is not None else int(cfg["end_age"]),
    }


async def upsert_inputs(conn, p: Dict[str, Any]) -> Dict[str, Any]:
    """PUT the singleton (id=1)."""
    await conn.execute(
        """
        INSERT INTO finance.retirement_inputs
            (id, current_age, retirement_age, current_balance, annual_salary,
             annual_contribution, annual_expenses, expected_return, inflation_rate,
             withdrawal_rate, end_age, updated_at)
        VALUES (1, $1,$2,$3,$4,$5,$6,$7,$8,$9,$10, now())
        ON CONFLICT (id) DO UPDATE SET
            current_age = EXCLUDED.current_age, retirement_age = EXCLUDED.retirement_age,
            current_balance = EXCLUDED.current_balance, annual_salary = EXCLUDED.annual_salary,
            annual_contribution = EXCLUDED.annual_contribution, annual_expenses = EXCLUDED.annual_expenses,
            expected_return = EXCLUDED.expected_return, inflation_rate = EXCLUDED.inflation_rate,
            withdrawal_rate = EXCLUDED.withdrawal_rate, end_age = EXCLUDED.end_age, updated_at = now()
        """,
        p.get("current_age"), p.get("retirement_age"), p.get("current_balance"),
        p.get("annual_salary"), p.get("annual_contribution"), p.get("annual_expenses"),
        p.get("expected_return"), p.get("inflation"), p.get("withdrawal_rate"), p.get("end_age"),
    )
    return await get_inputs(conn)


def _f(v) -> Optional[float]:
    return None if v is None else float(v)


def _pick(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _effective(saved: Dict[str, Any], cfg: Dict[str, float], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge precedence: live overrides → saved inputs → config defaults."""
    saved = saved or {}
    overrides = overrides or {}
    return {
        "current_age": _pick(overrides.get("current_age"), saved.get("current_age")),
        "retirement_age": _pick(overrides.get("retirement_age"), saved.get("retirement_age")),
        "current_balance": _pick(overrides.get("current_balance"), saved.get("current_balance")),
        "annual_contribution": _pick(overrides.get("annual_contribution"), saved.get("annual_contribution")),
        "annual_expenses": _pick(overrides.get("annual_expenses"), saved.get("annual_expenses")),
        "nominal_return": _pick(overrides.get("expected_return"), saved.get("expected_return"), cfg["nominal_return"]),
        "inflation": _pick(overrides.get("inflation"), saved.get("inflation_rate"), cfg["inflation"]),
        "withdrawal_rate": _pick(overrides.get("withdrawal_rate"), saved.get("withdrawal_rate"), cfg["withdrawal_rate"]),
        "end_age": _pick(overrides.get("end_age"), saved.get("end_age"), cfg["end_age"]),
    }


def _to_models(eff: Dict[str, Any]) -> tuple[RetirementInputs, Assumptions]:
    missing = [k for k in _REQUIRED if eff.get(k) is None]
    if missing:
        raise NeedsInputsError(f"missing required inputs: {missing}")
    current_age, retirement_age, end_age = int(eff["current_age"]), int(eff["retirement_age"]), int(eff["end_age"])
    if not (current_age < retirement_age <= end_age):
        raise RetirementValidationError("ages must satisfy current_age < retirement_age <= end_age")
    if Decimal(str(eff["withdrawal_rate"])) <= 0:
        raise RetirementValidationError("withdrawal_rate must be > 0")
    inputs = RetirementInputs(
        current_age=current_age, retirement_age=retirement_age,
        current_balance=Decimal(str(eff["current_balance"])),
        annual_contribution=Decimal(str(eff["annual_contribution"])),
        annual_expenses=Decimal(str(eff["annual_expenses"])),
    )
    assumptions = Assumptions(
        nominal_return=Decimal(str(eff["nominal_return"])),
        inflation=Decimal(str(eff["inflation"])),
        withdrawal_rate=Decimal(str(eff["withdrawal_rate"])),
        end_age=end_age,
    )
    return inputs, assumptions


def _serialize(series: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "series": [{"age": p["age"], "balance": float(p["balance"])} for p in series["series"]],
        "retirement_age": series["retirement_age"],
        "retirement_balance": float(series["retirement_balance"]),
        "fire_target": float(series["fire_target"]),
        "surplus_or_gap": float(series["surplus_or_gap"]),
        "on_track": series["on_track"],
        "depletion_age": series["depletion_age"],
        "required_monthly_contribution": float(stats["required_monthly_contribution"]),
        "earliest_age_on_track": stats["earliest_age_on_track"],
        "disclaimer": DISCLAIMER,   # R4.6 — non-nullable on every projection
    }


async def project(conn, overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Reactive projection: merge overrides over saved inputs over config, run the
    pure engine, return series + stats + disclaimer. Does NOT persist."""
    cfg = await load_config(conn)
    saved = await get_inputs(conn) or {}
    inputs, assumptions = _to_models(_effective(saved, cfg, overrides or {}))
    series = project_series(inputs, assumptions)
    stats = retire_at_age(inputs, assumptions)
    return _serialize(series, stats)


async def compare(conn, scenarios: List[Dict[str, Any]]) -> Dict[str, Any]:
    """R4.4: project each named scenario (overrides) and return them side by side."""
    cfg = await load_config(conn)
    saved = await get_inputs(conn) or {}
    out = []
    for sc in scenarios:
        inputs, assumptions = _to_models(_effective(saved, cfg, sc.get("overrides") or {}))
        series = project_series(inputs, assumptions)
        stats = retire_at_age(inputs, assumptions)
        out.append({"name": sc.get("name", "Scenario"), **_serialize(series, stats)})
    return {"scenarios": out}
