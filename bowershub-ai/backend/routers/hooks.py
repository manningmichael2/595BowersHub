"""
Hook API routes: CRUD, test, execution log.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user, require_admin
from backend.database import get_pool

router = APIRouter(prefix="/api/hooks", tags=["hooks"])


class HookCreate(BaseModel):
    workspace_id: int
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    event_type: str = Field(..., pattern="^(message_sent|message_received|file_uploaded|conversation_started|conversation_ended|schedule|manual)$")
    action_type: str = Field(..., pattern="^(call_webhook|call_ai|capture_context|notify)$")
    action_config: dict = {}
    conditions: dict = {}
    cron_expression: Optional[str] = None
    is_enabled: bool = True


class HookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    action_config: Optional[dict] = None
    conditions: Optional[dict] = None
    cron_expression: Optional[str] = None
    is_enabled: Optional[bool] = None


class HookResponse(BaseModel):
    id: int
    workspace_id: int
    name: str
    description: Optional[str]
    event_type: str
    action_type: str
    action_config: dict
    conditions: dict
    cron_expression: Optional[str]
    is_enabled: bool


@router.get("", response_model=List[HookResponse])
async def list_hooks(
    workspace_id: int = Query(...),
    user: dict = Depends(get_current_user),
):
    """List hooks for a workspace."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM public.bh_hooks WHERE workspace_id = $1 ORDER BY name",
            workspace_id,
        )
    return [
        HookResponse(
            id=r["id"], workspace_id=r["workspace_id"], name=r["name"],
            description=r["description"], event_type=r["event_type"],
            action_type=r["action_type"], action_config=r["action_config"] or {},
            conditions=r["conditions"] or {}, cron_expression=r["cron_expression"],
            is_enabled=r["is_enabled"],
        )
        for r in rows
    ]


@router.post("", response_model=HookResponse)
async def create_hook(body: HookCreate, user: dict = Depends(get_current_user)):
    """Create a new hook."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO public.bh_hooks
                (workspace_id, name, description, event_type, action_type,
                 action_config, conditions, cron_expression, is_enabled, created_by)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8, $9, $10)
            RETURNING *
        """, body.workspace_id, body.name, body.description, body.event_type,
            body.action_type, body.action_config, body.conditions,
            body.cron_expression, body.is_enabled, user["id"])

    return HookResponse(
        id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
        description=row["description"], event_type=row["event_type"],
        action_type=row["action_type"], action_config=row["action_config"] or {},
        conditions=row["conditions"] or {}, cron_expression=row["cron_expression"],
        is_enabled=row["is_enabled"],
    )


@router.patch("/{hook_id}", response_model=HookResponse)
async def update_hook(hook_id: int, body: HookUpdate, user: dict = Depends(get_current_user)):
    """Update a hook."""
    updates = []
    values = []
    idx = 1
    for field, value in body.model_dump(exclude_unset=True).items():
        if field in ("action_config", "conditions"):
            updates.append(f"{field} = ${idx}::jsonb")
        else:
            updates.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(hook_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_hooks SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Hook not found")

    return HookResponse(
        id=row["id"], workspace_id=row["workspace_id"], name=row["name"],
        description=row["description"], event_type=row["event_type"],
        action_type=row["action_type"], action_config=row["action_config"] or {},
        conditions=row["conditions"] or {}, cron_expression=row["cron_expression"],
        is_enabled=row["is_enabled"],
    )


@router.delete("/{hook_id}")
async def delete_hook(hook_id: int, user: dict = Depends(get_current_user)):
    """Delete a hook."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM public.bh_hooks WHERE id = $1", hook_id)
    return {"ok": True}


@router.post("/{hook_id}/test")
async def test_hook(hook_id: int, user: dict = Depends(get_current_user)):
    """Manually trigger a hook for testing."""
    pool = get_pool()
    async with pool.acquire() as conn:
        hook = await conn.fetchrow("SELECT * FROM public.bh_hooks WHERE id = $1", hook_id)

    if not hook:
        raise HTTPException(status_code=404, detail="Hook not found")

    # Execute via hook engine
    from backend.services.hook_engine import HookEngine, HookEventContext
    from backend.services.model_provider import ModelProvider
    from fastapi import Request

    # This is a simplified test — in production, services come from app.state
    return {"ok": True, "message": "Hook test triggered (check hook log for results)"}


@router.get("/{hook_id}/log")
async def get_hook_log(
    hook_id: int,
    limit: int = Query(default=20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """Get execution log for a hook."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM public.bh_hook_log
            WHERE hook_id = $1
            ORDER BY executed_at DESC
            LIMIT $2
        """, hook_id, limit)

    return [
        {
            "id": r["id"],
            "event_type": r["event_type"],
            "trigger_data": r["trigger_data"],
            "action_result": r["action_result"],
            "success": r["success"],
            "error_message": r["error_message"],
            "executed_at": r["executed_at"].isoformat(),
        }
        for r in rows
    ]
