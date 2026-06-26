"""Finance insights API (R2.5, R2.6).

Read the surfaced insights and act on them. Reads require an authenticated user;
every mutation requires require_admin (single-owner app). The "always categorize
{merchant} as {category}" rule-create action is added in Task 12 (it needs the
NL-rule path); this router owns dismiss / reopen / mark-actioned + the run log.
"""

from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException

from backend.database import get_pool
from backend.middleware.auth import require_capability
from backend.services.finance_insights import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/finance", tags=["finance-insights"])

_STATUSES = {"active", "dismissed", "actioned"}


@router.get("/insights")
async def list_insights(status: str = "active", user: dict = Depends(require_capability("finance.read"))) -> dict:
    if status != "all" and status not in _STATUSES:
        raise HTTPException(status_code=400, detail=f"invalid status; one of {sorted(_STATUSES)} or 'all'")
    try:
        async with get_pool().acquire() as conn:
            rows = await store.list_insights(conn, None if status == "all" else status)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        logger.warning("finance_insights: DB unavailable: %s", e)
        raise HTTPException(status_code=503, detail="Finance database unavailable.")
    # Serialize the columns the UI needs (figures/reason/impact + lifecycle).
    return {"insights": [
        {
            "id": r["id"], "insight_type": r["insight_type"], "merchant_key": r["merchant_key"],
            "period": r["period"], "status": r["status"], "dollar_impact": float(r["dollar_impact"]),
            "figures": r["figures"], "reason": r["reason"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        }
        for r in rows
    ]}


async def _mutate(insight_id: int, fn) -> dict:
    try:
        async with get_pool().acquire() as conn:
            ok = await fn(conn, insight_id)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        logger.warning("finance_insights: DB unavailable: %s", e)
        raise HTTPException(status_code=503, detail="Finance database unavailable.")
    if not ok:
        raise HTTPException(status_code=404, detail="insight not found")
    return {"ok": True}


@router.post("/insights/dismiss-all")
async def dismiss_all_insights(user: dict = Depends(require_capability("finance.insight.action"))) -> dict:
    """Dismiss every active insight at once — clears the queue in one call."""
    try:
        async with get_pool().acquire() as conn:
            count = await store.dismiss_all_active(conn)
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        logger.warning("finance_insights: DB unavailable: %s", e)
        raise HTTPException(status_code=503, detail="Finance database unavailable.")
    return {"dismissed": count}


@router.post("/insights/{insight_id}/dismiss")
async def dismiss_insight(insight_id: int, user: dict = Depends(require_capability("finance.insight.action"))) -> dict:
    return await _mutate(insight_id, store.dismiss)


@router.post("/insights/{insight_id}/reopen")
async def reopen_insight(insight_id: int, user: dict = Depends(require_capability("finance.insight.action"))) -> dict:
    return await _mutate(insight_id, store.reopen)


@router.post("/insights/{insight_id}/action")
async def action_insight(insight_id: int, user: dict = Depends(require_capability("finance.insight.action"))) -> dict:
    return await _mutate(insight_id, store.mark_actioned)


@router.get("/insights/runs/latest")
async def latest_run(user: dict = Depends(require_capability("finance.read"))) -> dict:
    try:
        async with get_pool().acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, started_at, finished_at, status, detected, suppressed, error "
                "FROM finance.insight_runs ORDER BY id DESC LIMIT 1"
            )
    except (asyncpg.PostgresError, OSError, RuntimeError) as e:
        raise HTTPException(status_code=503, detail="Finance database unavailable.")
    if row is None:
        return {"run": None}
    return {"run": {
        "id": row["id"],
        "started_at": row["started_at"].isoformat() if row["started_at"] else None,
        "finished_at": row["finished_at"].isoformat() if row["finished_at"] else None,
        "status": row["status"], "detected": row["detected"],
        "suppressed": row["suppressed"], "error": row["error"],
    }}
