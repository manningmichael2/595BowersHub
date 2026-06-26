"""Typed Finance Budgets API (finance-budgets-splits Task 6, R3.2/R3.3).

List/upsert per-category monthly budgets on the existing finance.budgets table,
and a budget-vs-actual read (allocation-aware via services/budgets). Mirrors
finance_review.py / finance_accounting.py: Pydantic in/out, reads via
get_current_user, writes via require_admin, DB-down → typed 503.
"""

from __future__ import annotations

import logging
from datetime import date

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from backend.database import get_pool
from backend.middleware.auth import require_capability
from backend.services.budgets import budget_vs_actual, list_budgets, upsert_budget

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance-budgets"])


class BudgetUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")  # anti-spoof: no *_by from the body (R4.1)
    category_id: int
    month: date           # any day in the month; normalized to the 1st
    limit_amount: float


def _db_error(e: Exception) -> HTTPException:
    logger.warning("finance_budgets: DB unavailable: %s", e)
    return HTTPException(status_code=503, detail="Finance database unavailable; no changes were made.")


def _first_of_month(d: date) -> date:
    return d.replace(day=1)


@router.get("/budgets")
async def get_budgets(month: date, user: dict = Depends(require_capability("finance.read"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return {"budgets": await list_budgets(conn, _first_of_month(month))}
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.get("/budgets/actual")
async def get_budget_actual(month: date, user: dict = Depends(require_capability("finance.read"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return {"month": _first_of_month(month).isoformat(),
                    "categories": await budget_vs_actual(conn, _first_of_month(month))}
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.put("/budgets")
async def put_budget(body: BudgetUpsert, user: dict = Depends(require_capability("finance.write"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            if not await conn.fetchval("SELECT 1 FROM finance.categories WHERE id = $1", body.category_id):
                raise HTTPException(status_code=400, detail="Unknown category_id")
            return await upsert_budget(conn, body.category_id, _first_of_month(body.month),
                                       body.limit_amount, actor_id=user["id"])
    except HTTPException:
        raise
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
