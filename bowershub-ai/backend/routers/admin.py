"""
Admin API routes: user management, cost dashboard, model rates, audit log.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from backend.middleware.auth import require_admin
from backend.database import get_pool

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserUpdate(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    display_name: Optional[str] = None


class ModelRateUpdate(BaseModel):
    input_cost_per_mtok: Optional[float] = None
    output_cost_per_mtok: Optional[float] = None
    supports_vision: Optional[bool] = None
    supports_tools: Optional[bool] = None


@router.get("/users")
async def list_users(user: dict = Depends(require_admin)):
    """List all users with their details."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, email, display_name, role, is_active, created_at, last_login_at
            FROM public.bh_users ORDER BY created_at
        """)
    return [dict(r) for r in rows]


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UserUpdate, user: dict = Depends(require_admin)):
    """Update a user's role or active status."""
    updates = []
    values = []
    idx = 1
    for field, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_users SET {', '.join(updates)} WHERE id = ${idx} RETURNING id, email, display_name, role, is_active",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    # Audit log
    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "modify_user", "user", user_id, body.model_dump(exclude_unset=True))

    return dict(row)


@router.get("/cost")
async def cost_dashboard(
    days: int = Query(default=7, ge=1, le=90),
    user: dict = Depends(require_admin),
):
    """Cost dashboard: daily totals, per-model/layer/workspace breakdown."""
    pool = get_pool()
    async with pool.acquire() as conn:
        # Daily totals
        daily = await conn.fetch("""
            SELECT DATE(called_at) as day,
                   COALESCE(SUM(cost_usd), 0) as total,
                   COUNT(*) as calls
            FROM public.api_usage_log
            WHERE called_at >= CURRENT_DATE - $1 * INTERVAL '1 day'
            GROUP BY DATE(called_at)
            ORDER BY day DESC
        """, days)

        # By model
        by_model = await conn.fetch("""
            SELECT model,
                   COALESCE(SUM(cost_usd), 0) as total,
                   COUNT(*) as calls,
                   COALESCE(SUM(input_tokens), 0) as input_tokens,
                   COALESCE(SUM(output_tokens), 0) as output_tokens
            FROM public.api_usage_log
            WHERE called_at >= CURRENT_DATE - $1 * INTERVAL '1 day'
            GROUP BY model ORDER BY total DESC
        """, days)

        # By source (workflow_name includes bowershub-ai/L1, bowershub-ai/L2, etc.)
        by_source = await conn.fetch("""
            SELECT workflow_name as source,
                   COALESCE(SUM(cost_usd), 0) as total,
                   COUNT(*) as calls
            FROM public.api_usage_log
            WHERE called_at >= CURRENT_DATE - $1 * INTERVAL '1 day'
            GROUP BY workflow_name ORDER BY total DESC
        """, days)

        # Today's total
        today_total = await conn.fetchval("""
            SELECT COALESCE(SUM(cost_usd), 0)
            FROM public.api_usage_log
            WHERE called_at >= CURRENT_DATE
        """)

    return {
        "today_total": float(today_total),
        "period_days": days,
        "daily": [{"day": r["day"].isoformat(), "total": float(r["total"]), "calls": r["calls"]} for r in daily],
        "by_model": [{"model": r["model"], "total": float(r["total"]), "calls": r["calls"],
                      "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"]} for r in by_model],
        "by_source": [{"source": r["source"], "total": float(r["total"]), "calls": r["calls"]} for r in by_source],
    }


@router.get("/models")
async def list_models(user: dict = Depends(require_admin)):
    """List all model rates."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM public.bh_model_rates ORDER BY provider, model_id")
    return [dict(r) for r in rows]


@router.patch("/models/{model_id}")
async def update_model_rate(model_id: int, body: ModelRateUpdate, user: dict = Depends(require_admin)):
    """Update model cost rates."""
    updates = []
    values = []
    idx = 1
    for field, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append(f"updated_at = now()")
    values.append(model_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_model_rates SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Model not found")
    return dict(row)


@router.get("/audit")
async def get_audit_log(
    limit: int = Query(default=50, ge=1, le=500),
    user_filter: Optional[int] = Query(default=None, alias="user_id"),
    user: dict = Depends(require_admin),
):
    """Get audit log entries."""
    from backend.middleware.audit import AuditLogger
    entries = await AuditLogger.get_recent(limit=limit, user_id=user_filter)
    # Serialize datetime fields
    return [
        {
            "id": e["id"],
            "user_id": e["user_id"],
            "user_email": e.get("user_email"),
            "action": e["action"],
            "target_type": e["target_type"],
            "target_id": e["target_id"],
            "details": e["details"],
            "ip_address": e["ip_address"],
            "created_at": e["created_at"].isoformat() if e["created_at"] else None,
        }
        for e in entries
    ]


@router.post("/run-categorizer")
async def run_categorizer_now(user: dict = Depends(require_admin)):
    """Trigger the transaction categorizer on-demand (uses local Ollama model)."""
    from backend.services.categorizer import run_categorizer
    result = await run_categorizer()
    return result
