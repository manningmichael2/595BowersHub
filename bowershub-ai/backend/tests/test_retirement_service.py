"""ai-finance-insights Task 15 — retirement service + endpoints (R4.*)."""

from __future__ import annotations

import pytest

from backend.database import close_pool, get_pool
from backend.services import retirement as svc
from backend.services.finance_projection import (
    Assumptions, RetirementInputs, retire_at_age,
)
from decimal import Decimal
from backend.tests.semantic_helpers import apply_migrations

# A complete set of override inputs (so projections run without saved inputs).
_BASE = {
    "current_age": 40, "retirement_age": 65, "current_balance": 100000,
    "annual_contribution": 12000, "annual_expenses": 40000,
    "expected_return": 0.07, "inflation": 0.03, "withdrawal_rate": 0.04, "end_age": 95,
}


@pytest.mark.asyncio
async def test_project_matches_engine_and_carries_disclaimer(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        async with get_pool().acquire() as conn:
            out = await svc.project(conn, {**_BASE, "retirement_age": 60})
        # Disclaimer present on every projection (R4.6).
        assert out["disclaimer"]
        assert out["retirement_age"] == 60
        # surplus/gap matches a direct engine computation (reference).
        inputs = RetirementInputs(
            current_age=40, retirement_age=60, current_balance=Decimal("100000"),
            annual_contribution=Decimal("12000"), annual_expenses=Decimal("40000"))
        assumptions = Assumptions(Decimal("0.07"), Decimal("0.03"), Decimal("0.04"), 95)
        ref = retire_at_age(inputs, assumptions, 60)
        assert abs(out["surplus_or_gap"] - float(ref["surplus_or_gap"])) < 1.0
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_no_inputs_is_cold_start(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        async with get_pool().acquire() as conn:
            assert await svc.has_inputs(conn) is False
            with pytest.raises(svc.NeedsInputsError):
                await svc.project(conn, {})   # no saved inputs, no overrides
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_whatif_override_recomputes(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        async with get_pool().acquire() as conn:
            low = await svc.project(conn, {**_BASE, "annual_contribution": 6000})
            high = await svc.project(conn, {**_BASE, "annual_contribution": 24000})
        # More contribution → larger retirement balance (reactive recompute).
        assert high["retirement_balance"] > low["retirement_balance"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_save_then_project_uses_saved_inputs(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        async with get_pool().acquire() as conn:
            await svc.upsert_inputs(conn, _BASE)
            assert await svc.has_inputs(conn) is True
            # Projection works with NO overrides now (saved inputs supply everything).
            out = await svc.project(conn, {})
            assert out["retirement_age"] == 65 and out["disclaimer"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_compare_returns_distinct_projections(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        async with get_pool().acquire() as conn:
            result = await svc.compare(conn, [
                {"name": "Retire at 60", "overrides": {**_BASE, "retirement_age": 60}},
                {"name": "Retire at 65", "overrides": {**_BASE, "retirement_age": 65}},
            ])
        names = [s["name"] for s in result["scenarios"]]
        assert names == ["Retire at 60", "Retire at 65"]
        bal60 = result["scenarios"][0]["retirement_balance"]
        bal65 = result["scenarios"][1]["retirement_balance"]
        assert bal65 > bal60   # distinct projections (R4.4)
        assert all(s["disclaimer"] for s in result["scenarios"])
    finally:
        await close_pool()
