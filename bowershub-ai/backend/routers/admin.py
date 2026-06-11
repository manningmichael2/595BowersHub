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
    # Closed whitelist — the f"{field} = ${idx}" builder in update_model_rate is safe
    # ONLY because these are typed Pydantic fields, never free-form column names (R5.1).
    model_config = {"extra": "forbid"}   # reject unknown fields outright
    input_cost_per_mtok: Optional[float] = None
    output_cost_per_mtok: Optional[float] = None
    supports_vision: Optional[bool] = None
    supports_tools: Optional[bool] = None
    is_active: Optional[bool] = None
    needs_price_confirmation: Optional[bool] = None


class AliasUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    model_id: str


async def _invalidate_resolver() -> None:
    """Rebuild the resolver cache after an admin edit so changes take effect at once.
    No-op when the resolver isn't initialized (e.g. unit tests without lifespan)."""
    try:
        from backend.services.model_catalog import get_resolver
        await get_resolver().reload()
    except RuntimeError:
        pass


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
    """Cost dashboard: daily totals, per-model/layer/workspace breakdown.
    
    Uses bh_messages as the primary source (has routing_layer, cost_usd, model_used
    per message). Falls back to api_usage_log for historical n8n data.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Daily totals from bh_messages
        daily = await conn.fetch("""
            SELECT DATE(created_at) as day,
                   COALESCE(SUM(cost_usd), 0) as total,
                   COUNT(*) FILTER (WHERE role = 'assistant') as responses
            FROM public.bh_messages
            WHERE created_at >= CURRENT_DATE - $1 * INTERVAL '1 day'
              AND cost_usd > 0
            GROUP BY DATE(created_at)
            ORDER BY day DESC
        """, days)

        # By model
        by_model = await conn.fetch("""
            SELECT model_used as model,
                   COALESCE(SUM(cost_usd), 0) as total,
                   COUNT(*) as calls,
                   COALESCE(SUM(input_tokens), 0) as input_tokens,
                   COALESCE(SUM(output_tokens), 0) as output_tokens
            FROM public.bh_messages
            WHERE created_at >= CURRENT_DATE - $1 * INTERVAL '1 day'
              AND model_used IS NOT NULL AND cost_usd > 0
            GROUP BY model_used ORDER BY total DESC
        """, days)

        # By routing layer
        by_layer = await conn.fetch("""
            SELECT routing_layer as layer,
                   COALESCE(SUM(cost_usd), 0) as total,
                   COUNT(*) as calls
            FROM public.bh_messages
            WHERE created_at >= CURRENT_DATE - $1 * INTERVAL '1 day'
              AND routing_layer IS NOT NULL
            GROUP BY routing_layer ORDER BY total DESC
        """, days)

        # By workspace
        by_workspace = await conn.fetch("""
            SELECT w.name as workspace,
                   COALESCE(SUM(m.cost_usd), 0) as total,
                   COUNT(*) as calls
            FROM public.bh_messages m
            JOIN public.bh_conversations c ON c.id = m.conversation_id
            JOIN public.bh_workspaces w ON w.id = c.workspace_id
            WHERE m.created_at >= CURRENT_DATE - $1 * INTERVAL '1 day'
              AND m.cost_usd > 0
            GROUP BY w.name ORDER BY total DESC
        """, days)

        # Today's total
        today_total = await conn.fetchval("""
            SELECT COALESCE(SUM(cost_usd), 0)
            FROM public.bh_messages
            WHERE created_at >= CURRENT_DATE AND cost_usd > 0
        """)

    return {
        "today_total": float(today_total),
        "period_days": days,
        "daily": [{"day": r["day"].isoformat(), "total": float(r["total"]), "responses": r["responses"]} for r in daily],
        "by_model": [{"model": r["model"], "total": float(r["total"]), "calls": r["calls"],
                      "input_tokens": r["input_tokens"], "output_tokens": r["output_tokens"]} for r in by_model],
        "by_layer": [{"layer": r["layer"], "total": float(r["total"]), "calls": r["calls"]} for r in by_layer],
        "by_workspace": [{"workspace": r["workspace"], "total": float(r["total"]), "calls": r["calls"]} for r in by_workspace],
    }


@router.get("/models")
async def list_models(user: dict = Depends(require_admin)):
    """List all model rates (incl. price, lifecycle, price-confirm flag) with the
    role aliases each model fills (R5.1)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.*,
                   ref.input_cost_per_mtok  AS ref_input_cost,
                   ref.output_cost_per_mtok AS ref_output_cost,
                   COALESCE(array_agg(a.role) FILTER (WHERE a.role IS NOT NULL), '{}') AS roles
            FROM public.bh_model_rates r
            LEFT JOIN public.bh_model_aliases a ON a.model_id = r.model_id
            LEFT JOIN LATERAL (
                SELECT input_cost_per_mtok, output_cost_per_mtok
                FROM public.bh_model_price_rules
                WHERE (provider IS NULL OR provider = r.provider)
                  AND r.model_id LIKE pattern
                ORDER BY priority DESC, length(pattern) DESC
                LIMIT 1
            ) ref ON true
            GROUP BY r.id, ref.input_cost_per_mtok, ref.output_cost_per_mtok
            ORDER BY r.provider, r.model_id
            """
        )
    return [dict(r) for r in rows]


@router.get("/models/price-rules")
async def list_model_price_rules(user: dict = Depends(require_admin)):
    """The canonical provisional-pricing rules (bh_model_price_rules, 0006) — the
    operator-curated reference of what each model family *should* cost, grounded in
    Anthropic's published rates. Discovery applies these to new models; surfaced here
    so the actual catalog prices can be double-checked against the reference."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT provider, pattern, input_cost_per_mtok, output_cost_per_mtok, priority, note "
            "FROM public.bh_model_price_rules ORDER BY priority DESC, pattern"
        )
    return [dict(r) for r in rows]


@router.get("/models/aliases")
async def list_model_aliases(user: dict = Depends(require_admin)):
    """The role -> model_id map ("current haiku/sonnet/opus/local")."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT role, model_id, updated_at FROM public.bh_model_aliases ORDER BY role")
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
    await _invalidate_resolver()   # price/lifecycle edits take effect immediately
    return dict(row)


@router.put("/models/aliases/{role}")
async def set_model_alias(role: str, body: AliasUpdate, user: dict = Depends(require_admin)):
    """Repoint a role ("current haiku/sonnet/opus/local") to another model (R5.1) —
    "change current Sonnet via the DB, no redeploy". Target must be an ACTIVE model."""
    pool = get_pool()
    async with pool.acquire() as conn:
        target = await conn.fetchrow(
            "SELECT is_active FROM public.bh_model_rates WHERE model_id = $1", body.model_id
        )
        if target is None:
            raise HTTPException(status_code=404, detail="model_id not in catalog")
        if not target["is_active"]:
            raise HTTPException(status_code=400, detail="cannot point a role at an inactive model")
        row = await conn.fetchrow(
            """
            INSERT INTO public.bh_model_aliases (role, model_id, updated_by, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (role) DO UPDATE SET model_id = EXCLUDED.model_id,
                                             updated_by = EXCLUDED.updated_by, updated_at = now()
            RETURNING role, model_id, updated_at
            """,
            role, body.model_id, user.get("id"),
        )
    await _invalidate_resolver()   # the router/ask_db tier now resolves to the new model
    return dict(row)


@router.post("/models/refresh")
async def refresh_models(request: Request, user: dict = Depends(require_admin)):
    """Trigger an immediate model-catalog discovery refresh (R2.3). Shares the
    single-flight lock with the scheduled job; runs even when the scheduled-write
    lever (`model_discovery_enabled`) is off — this is an explicit operator action."""
    catalog_refresh = getattr(request.app.state, "catalog_refresh", None)
    if catalog_refresh is None:
        raise HTTPException(status_code=503, detail="Model discovery not initialized")
    summary = await catalog_refresh.refresh(trigger="admin")
    return {
        "added": summary.added,
        "reactivated": summary.reactivated,
        "deactivated": summary.deactivated,
        "price_flagged": summary.price_flagged,
        "complete": summary.complete,
    }


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


# ---- Slash Commands CRUD ----

class SlashCommandCreate(BaseModel):
    command: str
    description: str
    skill_id: Optional[int] = None
    param_template: Optional[dict] = None
    workspace_id: Optional[int] = None
    flags: Optional[list] = None
    is_active: bool = True


class SlashCommandUpdate(BaseModel):
    description: Optional[str] = None
    skill_id: Optional[int] = None
    param_template: Optional[dict] = None
    workspace_id: Optional[int] = None
    flags: Optional[list] = None
    is_active: Optional[bool] = None


@router.get("/slash-commands")
async def list_slash_commands(user: dict = Depends(require_admin)):
    """List all slash commands with their flags and skill associations."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT sc.*, s.name as skill_name, w.name as workspace_name
            FROM public.bh_slash_commands sc
            LEFT JOIN public.bh_skills s ON s.id = sc.skill_id
            LEFT JOIN public.bh_workspaces w ON w.id = sc.workspace_id
            ORDER BY sc.command
        """)
    return [dict(r) for r in rows]


@router.post("/slash-commands")
async def create_slash_command(body: SlashCommandCreate, user: dict = Depends(require_admin)):
    """Create a new slash command."""
    import json
    if not body.command.startswith("/"):
        raise HTTPException(status_code=400, detail="Command must start with /")

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check for duplicates
        existing = await conn.fetchval(
            "SELECT id FROM public.bh_slash_commands WHERE command = $1 AND (workspace_id = $2 OR ($2 IS NULL AND workspace_id IS NULL))",
            body.command, body.workspace_id
        )
        if existing:
            raise HTTPException(status_code=409, detail=f"Command {body.command} already exists")

        row = await conn.fetchrow("""
            INSERT INTO public.bh_slash_commands (command, description, skill_id, param_template, workspace_id, flags, is_active)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6::jsonb, $7)
            RETURNING *
        """, body.command, body.description, body.skill_id,
            json.dumps(body.param_template or {}),
            body.workspace_id,
            json.dumps(body.flags or []),
            body.is_active,
        )

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "create_slash_command", "slash_command", row["id"], {"command": body.command})
    return dict(row)


@router.patch("/slash-commands/{cmd_id}")
async def update_slash_command(cmd_id: int, body: SlashCommandUpdate, user: dict = Depends(require_admin)):
    """Update a slash command's description, flags, or active status."""
    import json
    updates = []
    values = []
    idx = 1

    if body.description is not None:
        updates.append(f"description = ${idx}")
        values.append(body.description)
        idx += 1
    if body.skill_id is not None:
        updates.append(f"skill_id = ${idx}")
        values.append(body.skill_id)
        idx += 1
    if body.param_template is not None:
        updates.append(f"param_template = ${idx}::jsonb")
        values.append(json.dumps(body.param_template))
        idx += 1
    if body.workspace_id is not None:
        updates.append(f"workspace_id = ${idx}")
        values.append(body.workspace_id)
        idx += 1
    if body.flags is not None:
        updates.append(f"flags = ${idx}::jsonb")
        values.append(json.dumps(body.flags))
        idx += 1
    if body.is_active is not None:
        updates.append(f"is_active = ${idx}")
        values.append(body.is_active)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(cmd_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_slash_commands SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Command not found")

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "update_slash_command", "slash_command", cmd_id, body.model_dump(exclude_unset=True))
    return dict(row)


@router.delete("/slash-commands/{cmd_id}")
async def delete_slash_command(cmd_id: int, user: dict = Depends(require_admin)):
    """Delete a slash command."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("DELETE FROM public.bh_slash_commands WHERE id = $1 RETURNING command", cmd_id)
    if not row:
        raise HTTPException(status_code=404, detail="Command not found")

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "delete_slash_command", "slash_command", cmd_id, {"command": row["command"]})
    return {"ok": True, "deleted": row["command"]}


# ---- API Registry CRUD ----

class ApiRegistryCreate(BaseModel):
    name: str
    base_url: str
    description: str
    auth_type: str = "none"
    auth_config: Optional[dict] = None
    endpoints: list = []
    headers: Optional[dict] = None
    notes: Optional[str] = None


class ApiRegistryUpdate(BaseModel):
    base_url: Optional[str] = None
    description: Optional[str] = None
    auth_type: Optional[str] = None
    auth_config: Optional[dict] = None
    endpoints: Optional[list] = None
    headers: Optional[dict] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None


@router.get("/api-registry")
async def list_api_registry(user: dict = Depends(require_admin)):
    """List all registered APIs in the toolbox."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT * FROM public.bh_api_registry
            ORDER BY usage_count DESC, name
        """)
    return [dict(r) for r in rows]


@router.post("/api-registry")
async def create_api_registry(body: ApiRegistryCreate, user: dict = Depends(require_admin)):
    """Register a new API in the toolbox."""
    import json
    from backend.services.toolbox import register_api
    api_id = await register_api(
        name=body.name,
        base_url=body.base_url,
        description=body.description,
        endpoints=body.endpoints,
        auth_type=body.auth_type,
        auth_config=body.auth_config,
        headers=body.headers,
    )
    # Update notes separately if provided
    if body.notes:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("UPDATE public.bh_api_registry SET notes = $1 WHERE id = $2", body.notes, api_id)

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "register_api", "api_registry", api_id, {"name": body.name, "base_url": body.base_url})
    return {"ok": True, "id": api_id, "name": body.name}


@router.patch("/api-registry/{api_id}")
async def update_api_registry(api_id: int, body: ApiRegistryUpdate, user: dict = Depends(require_admin)):
    """Update an API registry entry."""
    import json
    updates = []
    values = []
    idx = 1

    if body.base_url is not None:
        updates.append(f"base_url = ${idx}")
        values.append(body.base_url)
        idx += 1
    if body.description is not None:
        updates.append(f"description = ${idx}")
        values.append(body.description)
        idx += 1
    if body.auth_type is not None:
        updates.append(f"auth_type = ${idx}")
        values.append(body.auth_type)
        idx += 1
    if body.auth_config is not None:
        updates.append(f"auth_config = ${idx}::jsonb")
        values.append(json.dumps(body.auth_config))
        idx += 1
    if body.endpoints is not None:
        updates.append(f"endpoints = ${idx}::jsonb")
        values.append(json.dumps(body.endpoints))
        idx += 1
    if body.headers is not None:
        updates.append(f"headers = ${idx}::jsonb")
        values.append(json.dumps(body.headers))
        idx += 1
    if body.is_active is not None:
        updates.append(f"is_active = ${idx}")
        values.append(body.is_active)
        idx += 1
    if body.notes is not None:
        updates.append(f"notes = ${idx}")
        values.append(body.notes)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(api_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_api_registry SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="API not found")

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "update_api_registry", "api_registry", api_id, body.model_dump(exclude_unset=True))
    return dict(row)


@router.delete("/api-registry/{api_id}")
async def delete_api_registry(api_id: int, user: dict = Depends(require_admin)):
    """Delete an API from the registry."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("DELETE FROM public.bh_api_registry WHERE id = $1 RETURNING name", api_id)
    if not row:
        raise HTTPException(status_code=404, detail="API not found")

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "delete_api_registry", "api_registry", api_id, {"name": row["name"]})
    return {"ok": True, "deleted": row["name"]}


# ---- Routing Patterns CRUD ----

class PatternCreate(BaseModel):
    rule: str
    rule_type: str = "regex"
    skill_id: int
    param_template: Optional[dict] = None
    description: Optional[str] = None
    priority: int = 100
    workspace_id: Optional[int] = None
    is_active: bool = True


class PatternUpdate(BaseModel):
    rule: Optional[str] = None
    rule_type: Optional[str] = None
    skill_id: Optional[int] = None
    param_template: Optional[dict] = None
    description: Optional[str] = None
    priority: Optional[int] = None
    workspace_id: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("/patterns")
async def list_patterns(user: dict = Depends(require_admin)):
    """List all routing patterns with their skill associations."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT p.*, s.name as skill_name, w.name as workspace_name
            FROM public.bh_patterns p
            JOIN public.bh_skills s ON s.id = p.skill_id
            LEFT JOIN public.bh_workspaces w ON w.id = p.workspace_id
            ORDER BY p.priority ASC, p.id
        """)
    return [dict(r) for r in rows]


@router.post("/patterns")
async def create_pattern(body: PatternCreate, user: dict = Depends(require_admin)):
    """Create a new routing pattern."""
    import json
    import re as re_module

    # Validate regex if rule_type is regex
    if body.rule_type == "regex":
        try:
            re_module.compile(body.rule)
        except re_module.error as e:
            raise HTTPException(status_code=400, detail=f"Invalid regex: {e}")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority, workspace_id, is_active)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8)
            RETURNING *
        """, body.rule, body.rule_type, body.skill_id,
            json.dumps(body.param_template or {}),
            body.description, body.priority, body.workspace_id, body.is_active,
        )

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "create_pattern", "pattern", row["id"], {"rule": body.rule, "skill_id": body.skill_id})
    return dict(row)


@router.patch("/patterns/{pattern_id}")
async def update_pattern(pattern_id: int, body: PatternUpdate, user: dict = Depends(require_admin)):
    """Update a routing pattern."""
    import json
    import re as re_module

    # Validate regex if being updated
    if body.rule and body.rule_type != "keyword":
        try:
            re_module.compile(body.rule)
        except re_module.error as e:
            raise HTTPException(status_code=400, detail=f"Invalid regex: {e}")

    updates = []
    values = []
    idx = 1

    for field in ["rule", "rule_type", "skill_id", "description", "priority", "workspace_id", "is_active"]:
        val = getattr(body, field, None)
        if val is not None:
            updates.append(f"{field} = ${idx}")
            values.append(val)
            idx += 1

    if body.param_template is not None:
        updates.append(f"param_template = ${idx}::jsonb")
        values.append(json.dumps(body.param_template))
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(pattern_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_patterns SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Pattern not found")

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "update_pattern", "pattern", pattern_id, body.model_dump(exclude_unset=True))
    return dict(row)


@router.delete("/patterns/{pattern_id}")
async def delete_pattern(pattern_id: int, user: dict = Depends(require_admin)):
    """Delete a routing pattern."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("DELETE FROM public.bh_patterns WHERE id = $1 RETURNING rule", pattern_id)
    if not row:
        raise HTTPException(status_code=404, detail="Pattern not found")

    from backend.middleware.audit import AuditLogger
    await AuditLogger.log(user["id"], "delete_pattern", "pattern", pattern_id, {"rule": row["rule"]})
    return {"ok": True, "deleted": row["rule"]}
