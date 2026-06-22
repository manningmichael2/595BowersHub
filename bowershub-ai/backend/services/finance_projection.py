"""Pure retirement projection engine (R4.2).

No DB, no network — just deterministic ``Decimal`` math, so it is exhaustively
unit-testable against a reference spreadsheet and reusable as the forecasting
seam (#2). Monthly compounding with ``monthly_rate = annual_rate / 12`` (APR
convention); contributions are supplied by a ``Callable[[int], Decimal]`` keyed
on the month index, so salary-growth / step-up contribution schedules are
expressible without changing the engine.

Everything is driven by *passed-in* inputs + assumptions (the owner wants the
projection reactive to user-entered fields — rate of return, salary, annual
contribution, withdrawal rate, ages); nothing is hardcoded here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, List, Optional

_CENTS = Decimal("0.01")
ZERO = Decimal("0")


def _D(x) -> Decimal:
    return x if isinstance(x, Decimal) else Decimal(str(x))


def _money(x: Decimal) -> Decimal:
    return x.quantize(_CENTS)


@dataclass(frozen=True)
class RetirementInputs:
    current_age: int
    retirement_age: int
    current_balance: Decimal
    annual_contribution: Decimal      # baseline; a contributions Callable can override
    annual_expenses: Decimal          # desired annual spend in retirement (today's $)


@dataclass(frozen=True)
class Assumptions:
    nominal_return: Decimal           # e.g. 0.07
    inflation: Decimal                # e.g. 0.03
    withdrawal_rate: Decimal          # e.g. 0.04 (the "4% rule")
    end_age: int                      # planning horizon, e.g. 95


# --- primitives -------------------------------------------------------------

def real_rate(nominal: Decimal, inflation: Decimal) -> Decimal:
    """Inflation-adjusted ("real") annual return: (1+nominal)/(1+inflation) − 1."""
    nominal, inflation = _D(nominal), _D(inflation)
    return (Decimal(1) + nominal) / (Decimal(1) + inflation) - Decimal(1)


def future_value(present: Decimal, annual_rate: Decimal, years: int,
                 monthly_contribution: Decimal = ZERO) -> Decimal:
    """FV of a present sum plus level monthly contributions, monthly-compounded."""
    bal = _D(present)
    r = _D(annual_rate) / Decimal(12)
    c = _D(monthly_contribution)
    for _ in range(int(years) * 12):
        bal = bal * (Decimal(1) + r) + c
    return bal


def fire_target(annual_expenses: Decimal, withdrawal_rate: Decimal) -> Decimal:
    """The nest egg that sustains ``annual_expenses`` at ``withdrawal_rate``
    (e.g. 4% → 25×). Withdrawal rate must be > 0."""
    wr = _D(withdrawal_rate)
    if wr <= 0:
        raise ValueError("withdrawal_rate must be > 0")
    return _money(_D(annual_expenses) / wr)


def coast_fire(current_balance: Decimal, annual_rate: Decimal, years: int,
               target: Decimal) -> dict:
    """Coast-FIRE: the balance that, with NO further contributions, grows to
    ``target`` in ``years``. ``is_coasting`` = today's balance already suffices."""
    grown = future_value(_D(current_balance), annual_rate, years)
    growth = future_value(Decimal(1), annual_rate, years)   # (1 + r/12)^(years*12)
    coast_number = _money(_D(target) / growth) if growth > 0 else _money(_D(target))
    return {
        "coast_number": coast_number,
        "is_coasting": _D(current_balance) >= coast_number,
        "projected_no_contrib": _money(grown),
    }


# --- whole-plan projections -------------------------------------------------

def retire_at_age(inputs: RetirementInputs, assumptions: Assumptions,
                  target_age: Optional[int] = None) -> dict:
    """Project to ``target_age`` (default the input's retirement_age) and compare
    the projected balance to the FIRE target → surplus or gap, the monthly
    contribution that would exactly close a gap, and the earliest age the target
    is met under the current plan."""
    age = inputs.retirement_age if target_age is None else int(target_age)
    years = max(0, age - inputs.current_age)
    monthly = _D(inputs.annual_contribution) / Decimal(12)

    projected = future_value(inputs.current_balance, assumptions.nominal_return, years, monthly)
    target = fire_target(inputs.annual_expenses, assumptions.withdrawal_rate)
    surplus_or_gap = _money(projected - target)

    # Monthly contribution to exactly hit target by ``age`` (solve the linear FV).
    # FV = P*(1+r)^n + C * annuity_factor  →  C = (target − P*(1+r)^n) / annuity_factor
    required_monthly = ZERO
    if years > 0:
        base = future_value(inputs.current_balance, assumptions.nominal_return, years)
        annuity_factor = future_value(ZERO, assumptions.nominal_return, years, Decimal(1))
        if annuity_factor > 0:
            need = (target - base) / annuity_factor
            required_monthly = _money(max(ZERO, need))

    return {
        "target_age": age,
        "projected_balance": _money(projected),
        "fire_target": target,
        "surplus_or_gap": surplus_or_gap,
        "on_track": surplus_or_gap >= 0,
        "required_monthly_contribution": required_monthly,
        "earliest_age_on_track": _earliest_age_on_track(inputs, assumptions, target),
    }


def _earliest_age_on_track(inputs: RetirementInputs, assumptions: Assumptions,
                           target: Decimal) -> Optional[int]:
    monthly = _D(inputs.annual_contribution) / Decimal(12)
    bal = _D(inputs.current_balance)
    r = _D(assumptions.nominal_return) / Decimal(12)
    age = inputs.current_age
    for month in range((assumptions.end_age - inputs.current_age) * 12):
        bal = bal * (Decimal(1) + r) + monthly
        if (month + 1) % 12 == 0:
            age += 1
            if bal >= target:
                return age
    return None


def project_series(inputs: RetirementInputs, assumptions: Assumptions,
                   contributions: Optional[Callable[[int], Decimal]] = None) -> dict:
    """Month-by-month balance from current age to end age, returned as yearly
    points. Before retirement: grow + contribute (``contributions(month)`` or the
    level annual_contribution). At/after retirement: grow + withdraw the
    inflation-adjusted annual_expenses. Reports the retirement-age balance, the
    FIRE target, the surplus/gap, and the depletion age (if the money runs out)."""
    r = _D(assumptions.nominal_return) / Decimal(12)
    level_monthly = _D(inputs.annual_contribution) / Decimal(12)
    contrib = contributions or (lambda _m: level_monthly)
    monthly_inflation = _D(assumptions.inflation) / Decimal(12)

    bal = _D(inputs.current_balance)
    months = max(0, (assumptions.end_age - inputs.current_age) * 12)
    series: List[dict] = [{"age": inputs.current_age, "balance": _money(bal)}]
    retirement_month = max(0, (inputs.retirement_age - inputs.current_age) * 12)
    base_monthly_expense = _D(inputs.annual_expenses) / Decimal(12)
    depletion_age: Optional[int] = None
    retirement_balance = None

    for month in range(months):
        bal = bal * (Decimal(1) + r)
        if month < retirement_month:
            bal += contrib(month)
        else:
            # Withdraw inflation-adjusted spending (grown from today's dollars).
            infl = (Decimal(1) + monthly_inflation) ** month
            bal -= base_monthly_expense * infl
            if bal < 0 and depletion_age is None:
                depletion_age = inputs.current_age + (month + 1) // 12
                bal = ZERO
        if (month + 1) % 12 == 0:
            age = inputs.current_age + (month + 1) // 12
            series.append({"age": age, "balance": _money(bal)})
        if month + 1 == retirement_month:
            retirement_balance = bal

    if retirement_balance is None:
        retirement_balance = bal
    target = fire_target(inputs.annual_expenses, assumptions.withdrawal_rate)
    return {
        "series": series,
        "retirement_age": inputs.retirement_age,
        "retirement_balance": _money(retirement_balance),
        "fire_target": target,
        "surplus_or_gap": _money(retirement_balance - target),
        "on_track": retirement_balance >= target,
        "depletion_age": depletion_age,
    }
