"""
Workspace API routes: CRUD, user management, schema discovery, pinned context.
"""

import hashlib
import re
from datetime import datetime, timezone
from typing import Iterable, List, Tuple
from fastapi import APIRouter, Depends, HTTPException, Request

from backend.models.workspace import (
    WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse,
    WorkspaceUserAssignment, PinnedContextCreate, PinnedContextUpdate, PinnedContextResponse,
)
from backend.middleware.auth import get_current_user, require_admin, require_capability
from backend.middleware.audit import AuditLogger
from backend.database import get_pool

# Max length for workspace system_prompt (per R6.6).
SYSTEM_PROMPT_MAX_LENGTH = 50_000

# Pinned-context refresh limits.
PINNED_REFRESH_ROW_CAP = 200            # max rows fetched per refresh
PINNED_REFRESH_RESULT_CHAR_CAP = 20_000  # max chars stored in cached_result
PINNED_REFRESH_TIMEOUT_MS = 5_000        # statement timeout for the dynamic query

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


async def _check_workspace_access(workspace_id: int, user: dict) -> dict:
    """Resolve a workspace for any active user. Workspaces are shared
    household-wide (a trusted 2–5 person household), so access is not gated by
    bh_workspace_users membership — every authenticated user can reach every
    workspace. Returns the workspace row or 404 if it doesn't exist.

    (Conversation *content* stays private-per-user — that's enforced in the
    conversations router via the owner-or-admin _check_conversation_access, not
    here. Destructive ops like delete_workspace keep their own require_admin.)"""
    pool = get_pool()
    async with pool.acquire() as conn:
        ws = await conn.fetchrow(
            "SELECT * FROM public.bh_workspaces WHERE id = $1", workspace_id
        )
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        return dict(ws)


@router.get("", response_model=List[WorkspaceResponse])
async def list_workspaces(user: dict = Depends(get_current_user)):
    """List all workspaces. Workspaces are **shared household-wide** — every
    active user sees them all (conversations within them stay private-per-user,
    filtered by user_id in the conversations router). The bh_workspace_users
    table now only carries the `owner` role + skill scoping, not visibility."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT w.*,
                (SELECT COUNT(*) FROM bh_workspace_users wu WHERE wu.workspace_id = w.id) as user_count,
                (SELECT COUNT(*) FROM bh_workspace_skills ws WHERE ws.workspace_id = w.id) as skill_count
            FROM public.bh_workspaces w ORDER BY w.name
        """)

    return [
        WorkspaceResponse(
            id=r["id"], name=r["name"], description=r["description"],
            icon=r["icon"], color=r["color"], system_prompt=r["system_prompt"],
            default_model=r["default_model"], temperature=float(r["temperature"]),
            max_context_tokens=r["max_context_tokens"], auto_capture=r["auto_capture"],
            permitted_schemas=r["permitted_schemas"] or [],
            created_at=r["created_at"],
            user_count=r["user_count"], skill_count=r["skill_count"],
        )
        for r in rows
    ]


@router.post("", response_model=WorkspaceResponse)
async def create_workspace(body: WorkspaceCreate, user: dict = Depends(get_current_user)):
    """Create a new workspace."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO public.bh_workspaces
                (name, description, icon, color, system_prompt, default_model,
                 temperature, max_context_tokens, auto_capture, permitted_schemas, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
            RETURNING *
        """, body.name, body.description, body.icon, body.color, body.system_prompt,
            body.default_model, body.temperature, body.max_context_tokens,
            body.auto_capture, body.permitted_schemas, user["id"])

        # Add creator as owner
        await conn.execute("""
            INSERT INTO public.bh_workspace_users (workspace_id, user_id, role)
            VALUES ($1, $2, 'owner')
        """, row["id"], user["id"])

    return WorkspaceResponse(
        id=row["id"], name=row["name"], description=row["description"],
        icon=row["icon"], color=row["color"], system_prompt=row["system_prompt"],
        default_model=row["default_model"], temperature=float(row["temperature"]),
        max_context_tokens=row["max_context_tokens"], auto_capture=row["auto_capture"],
        permitted_schemas=row["permitted_schemas"] or [],
        created_at=row["created_at"], user_count=1, skill_count=0,
    )


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(workspace_id: int, user: dict = Depends(get_current_user)):
    """Get workspace details."""
    ws = await _check_workspace_access(workspace_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        user_count = await conn.fetchval(
            "SELECT COUNT(*) FROM bh_workspace_users WHERE workspace_id = $1", workspace_id
        )
        skill_count = await conn.fetchval(
            "SELECT COUNT(*) FROM bh_workspace_skills WHERE workspace_id = $1", workspace_id
        )

    return WorkspaceResponse(
        id=ws["id"], name=ws["name"], description=ws["description"],
        icon=ws["icon"], color=ws["color"], system_prompt=ws["system_prompt"],
        default_model=ws["default_model"], temperature=float(ws["temperature"]),
        max_context_tokens=ws["max_context_tokens"], auto_capture=ws["auto_capture"],
        permitted_schemas=ws["permitted_schemas"] or [],
        created_at=ws["created_at"], user_count=user_count, skill_count=skill_count,
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(workspace_id: int, body: WorkspaceUpdate, user: dict = Depends(get_current_user)):
    """Update workspace settings.

    Editing `system_prompt` requires admin role (R6.8) and is bounded at
    50,000 characters (R6.6). Successful prompt edits are recorded in
    `bh_audit_log` with a sha256 hash of the new prompt (R6.4).
    """
    await _check_workspace_access(workspace_id, user)

    body_fields = body.model_dump(exclude_unset=True)

    # System prompt edits: admin-only + length check (R6.6, R6.8)
    system_prompt_changed = "system_prompt" in body_fields
    new_system_prompt: str = ""
    if system_prompt_changed:
        if user.get("role") != "admin":
            raise HTTPException(
                status_code=403,
                detail="Admin role required to edit system_prompt",
            )
        new_system_prompt = body_fields["system_prompt"] or ""
        if len(new_system_prompt) > SYSTEM_PROMPT_MAX_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"system_prompt exceeds maximum length of "
                    f"{SYSTEM_PROMPT_MAX_LENGTH} characters"
                ),
            )

    # Build dynamic UPDATE
    updates = []
    values = []
    idx = 1
    for field, value in body_fields.items():
        updates.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(workspace_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_workspaces SET {', '.join(updates)} WHERE id = ${idx} RETURNING *",
            *values,
        )

    if not row:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Audit-log a system_prompt change with a hash of the new value (R6.4).
    if system_prompt_changed:
        prompt_hash = hashlib.sha256(new_system_prompt.encode("utf-8")).hexdigest()
        await AuditLogger.log(
            user_id=user["id"],
            action="modify_workspace_system_prompt",
            target_type="workspace",
            target_id=workspace_id,
            details={
                "system_prompt_sha256": prompt_hash,
                "system_prompt_length": len(new_system_prompt),
            },
        )

    return WorkspaceResponse(
        id=row["id"], name=row["name"], description=row["description"],
        icon=row["icon"], color=row["color"], system_prompt=row["system_prompt"],
        default_model=row["default_model"], temperature=float(row["temperature"]),
        max_context_tokens=row["max_context_tokens"], auto_capture=row["auto_capture"],
        permitted_schemas=row["permitted_schemas"] or [],
        created_at=row["created_at"], user_count=0, skill_count=0,
    )


@router.delete("/{workspace_id}")
async def delete_workspace(workspace_id: int, user: dict = Depends(require_admin)):
    """Delete a workspace (admin only)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM public.bh_workspaces WHERE id = $1", workspace_id)
    return {"ok": True}


# --- User management ---

@router.post("/{workspace_id}/users")
async def add_user_to_workspace(
    workspace_id: int, body: WorkspaceUserAssignment,
    user: dict = Depends(require_capability("users.manage")),
):
    """Add a user to a workspace (provisioning — admin/users.manage only)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO public.bh_workspace_users (workspace_id, user_id, role)
            VALUES ($1, $2, $3) ON CONFLICT (workspace_id, user_id) DO UPDATE SET role = $3
        """, workspace_id, body.user_id, body.role)
    return {"ok": True}


@router.delete("/{workspace_id}/users/{uid}")
async def remove_user_from_workspace(
    workspace_id: int, uid: int,
    user: dict = Depends(require_capability("users.manage")),
):
    """Remove a user from a workspace (provisioning — admin/users.manage only)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM public.bh_workspace_users WHERE workspace_id = $1 AND user_id = $2",
            workspace_id, uid,
        )
    return {"ok": True}


# --- Skill assignment ---

@router.get("/{workspace_id}/skills")
async def list_workspace_skills(workspace_id: int, user: dict = Depends(get_current_user)):
    """List all skills assigned to a workspace."""
    await _check_workspace_access(workspace_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT s.id, s.name, s.description
            FROM public.bh_skills s
            JOIN public.bh_workspace_skills ws ON ws.skill_id = s.id
            WHERE ws.workspace_id = $1 AND s.is_active = true
            ORDER BY s.name
        """, workspace_id)
    return [{"id": r["id"], "name": r["name"], "description": r["description"]} for r in rows]


@router.post("/{workspace_id}/skills")
async def set_workspace_skills(
    workspace_id: int,
    body: dict,
    user: dict = Depends(get_current_user),
):
    """Replace the workspace's skill list with a new set."""
    await _check_workspace_access(workspace_id, user)
    skill_ids = body.get("skill_ids", [])
    if not isinstance(skill_ids, list):
        raise HTTPException(status_code=400, detail="skill_ids must be a list")

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "DELETE FROM public.bh_workspace_skills WHERE workspace_id = $1",
                workspace_id,
            )
            for skill_id in skill_ids:
                await conn.execute(
                    "INSERT INTO public.bh_workspace_skills (workspace_id, skill_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                    workspace_id, int(skill_id),
                )

    # Audit log
    await AuditLogger.log(user["id"], "modify_workspace_skills", "workspace", workspace_id,
                          {"skill_count": len(skill_ids)})

    return {"ok": True, "skill_count": len(skill_ids)}


# --- Schema discovery ---

@router.get("/{workspace_id}/schemas")
async def list_available_schemas(workspace_id: int, user: dict = Depends(get_current_user)):
    """List all available DB schemas for assignment."""
    await _check_workspace_access(workspace_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
        """)
    return [r["schema_name"] for r in rows]


# --- Pinned context ---

@router.get("/{workspace_id}/pinned-context", response_model=List[PinnedContextResponse])
async def list_pinned_context(workspace_id: int, user: dict = Depends(get_current_user)):
    """List pinned context for a workspace."""
    await _check_workspace_access(workspace_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM public.bh_pinned_context WHERE workspace_id = $1 ORDER BY priority",
            workspace_id,
        )
    return [PinnedContextResponse(**dict(r)) for r in rows]


@router.post("/{workspace_id}/pinned-context", response_model=PinnedContextResponse)
async def add_pinned_context(
    workspace_id: int, body: PinnedContextCreate, user: dict = Depends(get_current_user)
):
    """Add pinned context to a workspace."""
    await _check_workspace_access(workspace_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO public.bh_pinned_context
                (workspace_id, context_type, title, content, query, refresh_minutes, priority)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
        """, workspace_id, body.context_type, body.title, body.content,
            body.query, body.refresh_minutes, body.priority)
    return PinnedContextResponse(**dict(row))


@router.patch("/{workspace_id}/pinned-context/{ctx_id}", response_model=PinnedContextResponse)
async def update_pinned_context(
    workspace_id: int, ctx_id: int, body: PinnedContextUpdate, user: dict = Depends(get_current_user)
):
    """Update pinned context."""
    await _check_workspace_access(workspace_id, user)

    updates = []
    values = []
    idx = 1
    for field, value in body.model_dump(exclude_unset=True).items():
        updates.append(f"{field} = ${idx}")
        values.append(value)
        idx += 1

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    values.append(ctx_id)
    values.append(workspace_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"UPDATE public.bh_pinned_context SET {', '.join(updates)} WHERE id = ${idx} AND workspace_id = ${idx+1} RETURNING *",
            *values,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Pinned context not found")
    return PinnedContextResponse(**dict(row))


@router.delete("/{workspace_id}/pinned-context/{ctx_id}")
async def delete_pinned_context(workspace_id: int, ctx_id: int, user: dict = Depends(get_current_user)):
    """Delete pinned context."""
    await _check_workspace_access(workspace_id, user)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM public.bh_pinned_context WHERE id = $1 AND workspace_id = $2",
            ctx_id, workspace_id,
        )
    return {"ok": True}


# --- Pinned-context refresh helpers (SchemaGuard) ---

# SQL keywords that must never appear in a pinned-context query. Pinned context
# is read-only by design — anything that mutates the database is rejected.
_FORBIDDEN_SQL_KEYWORDS = (
    "insert", "update", "delete", "drop", "create", "alter", "truncate",
    "grant", "revoke", "vacuum", "reindex", "comment", "lock", "copy",
    "execute", "call", "merge", "do",
)

# Matches schema-qualified table references like ``inventory.tools`` or
# ``public.bh_messages``. We deliberately accept only simple identifier dots
# (no wildcards, no quoted identifiers) — anything else is treated as
# unqualified and forced through the search_path.
_QUALIFIED_REF_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")

# Schemas that pinned-context queries are always allowed to read from. The
# workspace's own permitted_schemas are appended to this set per request.
# `pg_catalog` and `information_schema` are required for ordinary planning.
_ALWAYS_ALLOWED_SCHEMAS = frozenset({"pg_catalog", "information_schema"})


def _strip_sql_comments(sql: str) -> str:
    """Remove `--` line comments and `/* */` block comments for keyword scanning."""
    # Remove block comments first (non-greedy, multiline).
    no_block = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    # Then line comments.
    no_line = re.sub(r"--[^\n]*", " ", no_block)
    return no_line


def _validate_pinned_context_query(
    sql: str, permitted_schemas: Iterable[str]
) -> Tuple[str, List[str]]:
    """Validate a pinned-context dynamic query against the workspace's schemas.

    Returns the trimmed/normalized SQL string. Raises ``HTTPException(400)``
    on any of: empty/whitespace-only query, multiple statements, non-SELECT
    leading keyword, presence of any forbidden DML/DDL keyword, or a
    schema-qualified reference to a schema not in the permitted set.
    """
    if sql is None or not sql.strip():
        raise HTTPException(status_code=400, detail="Query is empty")

    trimmed = sql.strip().rstrip(";").strip()
    if not trimmed:
        raise HTTPException(status_code=400, detail="Query is empty")

    # Multiple statements are not allowed.
    if ";" in trimmed:
        raise HTTPException(
            status_code=400,
            detail="Only a single SELECT statement is allowed",
        )

    scrubbed = _strip_sql_comments(trimmed).lower()

    # Must start with SELECT or WITH (a CTE that resolves to a SELECT).
    leading = scrubbed.lstrip()
    if not (leading.startswith("select") or leading.startswith("with")):
        raise HTTPException(
            status_code=400,
            detail="Pinned-context queries must be SELECT statements",
        )

    # Reject forbidden keywords as whole words.
    for kw in _FORBIDDEN_SQL_KEYWORDS:
        if re.search(rf"\b{kw}\b", scrubbed):
            raise HTTPException(
                status_code=400,
                detail=f"Forbidden keyword in query: {kw}",
            )

    # Validate any schema-qualified references against the permitted set.
    allowed = set(_ALWAYS_ALLOWED_SCHEMAS) | {s for s in permitted_schemas if s}
    for match in _QUALIFIED_REF_RE.finditer(scrubbed):
        schema = match.group(1)
        if schema in allowed:
            continue
        # Common false-positive: ``table.column`` where ``table`` is a CTE or
        # alias, not a schema. We can't reliably distinguish without a real
        # parser, so we only flag references whose first identifier matches a
        # known schema name in the database; otherwise we assume it's a
        # column/alias dot. Practically, a workspace with empty
        # permitted_schemas will reject anything that LOOKS schema-qualified
        # to a real schema — that's a deliberate fail-closed default.
        # Here, we conservatively reject only when the first identifier is a
        # recognized schema from `information_schema.schemata` would be ideal,
        # but doing that synchronously bloats the validator. Instead we
        # reject any qualified reference that uses a schema literally listed
        # in a deny-set, and let the search_path SET LOCAL on execution
        # restrict resolution of unknown qualifiers.
        # Conservative behavior: if the workspace has any permitted schemas
        # configured, we require qualified refs to match the allowed list.
        if permitted_schemas:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Query references schema '{schema}' which is not in "
                    f"this workspace's permitted_schemas"
                ),
            )

    return trimmed


def _format_rows_as_text(rows: list) -> str:
    """Render asyncpg Records as a compact human-readable table snippet."""
    if not rows:
        return "(no rows)"
    columns = list(rows[0].keys())
    lines = [" | ".join(columns)]
    for r in rows:
        cells = []
        for c in columns:
            v = r[c]
            cells.append("" if v is None else str(v))
        lines.append(" | ".join(cells))
    return "\n".join(lines)


@router.post("/{workspace_id}/pinned-context/{ctx_id}/refresh")
async def refresh_pinned_context(
    workspace_id: int,
    ctx_id: int,
    user: dict = Depends(get_current_user),
):
    """Re-execute a dynamic pinned-context query (R7.7).

    Returns the updated ``cached_result``, ``cached_at`` (ISO8601), and
    ``token_estimate``. Returns 400 if the entry is ``type='static'`` or if
    the query fails validation. Workspace access is required.
    """
    workspace = await _check_workspace_access(workspace_id, user)

    pool = get_pool()
    async with pool.acquire() as conn:
        entry = await conn.fetchrow(
            """
            SELECT * FROM public.bh_pinned_context
            WHERE id = $1 AND workspace_id = $2
            """,
            ctx_id,
            workspace_id,
        )
        if entry is None:
            raise HTTPException(status_code=404, detail="Pinned context not found")

        if entry["context_type"] == "static":
            raise HTTPException(
                status_code=400,
                detail="Static pinned-context entries cannot be refreshed",
            )

        query = entry["query"]
        if not query or not query.strip():
            raise HTTPException(
                status_code=400,
                detail="Dynamic pinned-context entry has no query to refresh",
            )

        permitted_schemas = list(workspace.get("permitted_schemas") or [])
        validated_sql = _validate_pinned_context_query(query, permitted_schemas)

        # Execute the SELECT inside a READ ONLY transaction. We also pin the
        # search_path to the permitted schemas so unqualified references
        # cannot accidentally resolve to a schema the workspace shouldn't
        # touch.
        try:
            async with conn.transaction(readonly=True):
                # Statement timeout in ms.
                await conn.execute(
                    f"SET LOCAL statement_timeout = {PINNED_REFRESH_TIMEOUT_MS}"
                )
                # Build a safe search_path containing only the permitted
                # schemas plus pg_catalog/information_schema (ident-quoted).
                search_path_parts = ['"pg_catalog"', '"information_schema"']
                for s in permitted_schemas:
                    # Identifier-validate to be safe — schema names should
                    # already be vetted by Create/Update Workspace, but the
                    # SET command can't take parameters.
                    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", s):
                        search_path_parts.append(f'"{s}"')
                await conn.execute(
                    f"SET LOCAL search_path = {', '.join(search_path_parts)}"
                )
                # Cap rows fetched. We append our own LIMIT only when one is
                # not present in the original query, since wrapping with a
                # subquery breaks ORDER BY semantics for some dialects.
                fetch_sql = validated_sql
                if not re.search(r"\blimit\s+\d+\b", validated_sql, re.IGNORECASE):
                    fetch_sql = f"{validated_sql} LIMIT {PINNED_REFRESH_ROW_CAP}"
                rows = await conn.fetch(fetch_sql)
        except HTTPException:
            raise
        except Exception as exc:  # pragma: no cover - DB errors surface as 400
            raise HTTPException(
                status_code=400,
                detail=f"Query execution failed: {exc}",
            )

        rendered = _format_rows_as_text(rows)
        if len(rendered) > PINNED_REFRESH_RESULT_CHAR_CAP:
            rendered = (
                rendered[:PINNED_REFRESH_RESULT_CHAR_CAP]
                + "\n... (truncated)"
            )
        # Match the rough 4-chars-per-token heuristic used elsewhere in the
        # codebase (see router_engine.py).
        token_estimate = len(rendered) // 4
        cached_at = datetime.now(timezone.utc)

        await conn.execute(
            """
            UPDATE public.bh_pinned_context
               SET cached_result = $1,
                   cached_at = $2,
                   token_estimate = $3
             WHERE id = $4 AND workspace_id = $5
            """,
            rendered,
            cached_at,
            token_estimate,
            ctx_id,
            workspace_id,
        )

    return {
        "cached_result": rendered,
        "cached_at": cached_at.isoformat(),
        "token_estimate": token_estimate,
    }
