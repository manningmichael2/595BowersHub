"""ai-finance-insights Task 13 — pure projection engine (R4.2). No DB/network."""

from __future__ import annotations

from decimal import Decimal

from backend.services.finance_projection import (
    Assumptions, RetirementInputs, coast_fire, fire_target, future_value,
    project_series, real_rate, retire_at_age,
)


def _inputs(current_age=40, retirement_age=65, balance="100000",
            contribution="12000", expenses="40000"):
    return RetirementInputs(
        current_age=current_age, retirement_age=retirement_age,
        current_balance=Decimal(balance), annual_contribution=Decimal(contribution),
        annual_expenses=Decimal(expenses),
    )


_ASSUMPTIONS = Assumptions(
    nominal_return=Decimal("0.07"), inflation=Decimal("0.03"),
    withdrawal_rate=Decimal("0.04"), end_age=95,
)


def test_zero_contribution_fv_matches_independent_formula():
    fv = future_value(Decimal("10000"), Decimal("0.07"), 10, Decimal("0"))
    expected = 10000 * (1 + 0.07 / 12) ** 120  # independent float computation
    assert abs(float(fv) - expected) < 1.0


def test_fire_target_is_25x_at_4pct():
    assert fire_target(Decimal("40000"), Decimal("0.04")) == Decimal("1000000.00")


def test_real_rate_is_inflation_adjusted():
    rr = real_rate(Decimal("0.07"), Decimal("0.03"))
    assert abs(float(rr) - ((1.07 / 1.03) - 1)) < 1e-9


def test_coast_fire_boundary():
    target = Decimal("1000000")
    cf = coast_fire(Decimal("0"), Decimal("0.07"), 25, target)
    cn = cf["coast_number"]
    # Exactly at the coast number → coasting; a dollar under → not.
    assert coast_fire(cn, Decimal("0.07"), 25, target)["is_coasting"] is True
    assert coast_fire(cn - Decimal("1"), Decimal("0.07"), 25, target)["is_coasting"] is False


def test_retire_at_65_beats_retire_at_60():
    inp = _inputs()
    at60 = retire_at_age(inp, _ASSUMPTIONS, 60)
    at65 = retire_at_age(inp, _ASSUMPTIONS, 65)
    assert at65["projected_balance"] > at60["projected_balance"]
    # Both expose surplus/gap + the contribution that would close a gap.
    assert "surplus_or_gap" in at60 and "required_monthly_contribution" in at60


def test_gap_requires_positive_contribution_surplus_requires_none():
    # Tiny balance/contribution → a gap → a positive required contribution.
    poor = retire_at_age(_inputs(balance="1000", contribution="600"), _ASSUMPTIONS, 65)
    assert poor["surplus_or_gap"] < 0
    assert poor["required_monthly_contribution"] > 0
    # Huge balance → surplus → no extra contribution required.
    rich = retire_at_age(_inputs(balance="5000000", contribution="0"), _ASSUMPTIONS, 65)
    assert rich["surplus_or_gap"] > 0
    assert rich["required_monthly_contribution"] == Decimal("0.00")


def test_fv_monotonic_in_contribution():
    prev = None
    for c in range(0, 2000, 250):
        fv = future_value(Decimal("10000"), Decimal("0.07"), 20, Decimal(c))
        if prev is not None:
            assert fv > prev
        prev = fv


def test_project_series_shape_and_retirement_balance():
    inp = _inputs()
    out = project_series(inp, _ASSUMPTIONS)
    # One point per year from current age through end age.
    assert out["series"][0]["age"] == 40
    assert out["series"][-1]["age"] == 95
    # Retirement balance equals the standalone retire_at_age projection (same math).
    direct = retire_at_age(inp, _ASSUMPTIONS, 65)["projected_balance"]
    assert abs(float(out["retirement_balance"]) - float(direct)) < 1.0
    assert "depletion_age" in out and "surplus_or_gap" in out
