"""Retirement planner API (R4.1, R4.3, R4.4, R4.6, R4.8).

Reads require an authenticated user; saving inputs requires require_admin
(single-owner). /project is reactive — it recomputes from the posted overrides
without persisting, so the UI can recompute live on every field change. Every
projection response carries the disclaimer (R4.6).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.database import get_pool
from backend.middleware.auth import require_capability
from backend.services import retirement as svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance/retirement", tags=["finance-retirement"])


class InputsPayload(BaseModel):
    current_age: Optional[int] = None
    retirement_age: Optional[int] = None
    current_balance: Optional[float] = None
    annual_salary: Optional[float] = None
    annual_contribution: Optional[float] = None
    annual_expenses: Optional[float] = None
    expected_return: Optional[float] = None
    inflation: Optional[float] = None
    withdrawal_rate: Optional[float] = None
    end_age: Optional[int] = None


class ProjectRequest(BaseModel):
    overrides: Dict[str, Any] = {}


class ScenarioSpec(BaseModel):
    name: str
    overrides: Dict[str, Any] = {}


class CompareRequest(BaseModel):
    scenarios: List[ScenarioSpec]


def _db_error(e: Exception) -> HTTPException:
    logger.warning("retirement: DB unavailable: %s", e)
    return HTTPException(status_code=503, detail="Finance database unavailable.")


@router.get("/inputs")
async def get_inputs(user: dict = Depends(require_capability("finance.read"))) -> dict:
    """Current inputs + the prefilled form (R4.1) + a cold-start flag (R4.8)."""
    try:
        async with get_pool().acquire() as conn:
            return {"has_inputs": await svc.has_inputs(conn), "prefill": await svc.prefill(conn)}
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.put("/inputs")
async def put_inputs(body: InputsPayload, user: dict = Depends(require_capability("finance.write"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            saved = await svc.upsert_inputs(conn, body.model_dump())
        return {"saved": {k: (float(v) if hasattr(v, "is_finite") else v) for k, v in saved.items()}}
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.post("/project")
async def project(body: ProjectRequest, user: dict = Depends(require_capability("finance.read"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await svc.project(conn, body.overrides)
    except svc.NeedsInputsError:
        # Cold-start (R4.8): don't fabricate a projection — signal the UI to set up.
        return {"needs_inputs": True, "disclaimer": svc.DISCLAIMER}
    except svc.RetirementValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)


@router.post("/scenarios/compare")
async def compare(body: CompareRequest, user: dict = Depends(require_capability("finance.read"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            return await svc.compare(conn, [s.model_dump() for s in body.scenarios])
    except svc.NeedsInputsError:
        return {"needs_inputs": True, "disclaimer": svc.DISCLAIMER}
    except svc.RetirementValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise _db_error(e)
