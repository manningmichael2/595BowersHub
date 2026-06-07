"""
Briefing API routes — backs the proactive Morning Card.

Endpoints:
    GET  /api/briefing/latest?workspace_id=X
        Returns the most recent ``system`` briefing message in the user's
        morning-card workspace, parsed into the five canonical sections.
        Returns ``{"briefing_id": null}`` when no briefing exists within
        the last 24 hours so the frontend can offer a "Generate now"
        button instead of stale content (R8.3).

    POST /api/briefing/generate-now?workspace_id=X
        Calls the existing ``BriefingService.generate()``, persists the
        result as a system message in the workspace's "Daily Briefing"
        conversation, and returns the same shape as GET.

Workspace access uses the same pattern as the workspaces router
(``_check_workspace_access``): admins see every workspace, members must
be assigned to the workspace, anyone else gets 403.

Validates: Requirements R8.1, R8.3, R8.4, R8.7
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from backend.database import get_pool
from backend.middleware.auth import get_current_user
from backend.routers.workspaces import _check_workspace_access
from backend.services.briefing import BriefingService
from backend.services.briefing_summary import parse_sections

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/briefing", tags=["briefing"])


# Default workspace name when the caller doesn't pass workspace_id and the
# user hasn't set a morning_card_workspace_id in settings_json (R8.9: the
# default is the General workspace).
_DEFAULT_WORKSPACE_NAME = "General"

# Recency window for considering a briefing "fresh enough" to render in
# the Morning Card (R8.1). Older briefings are treated as absent so the
# frontend can offer a regeneration button (R8.3).
_BRIEFING_FRESH_HOURS = 24


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _resolve_workspace_id(user: dict, workspace_id: Optional[int]) -> int:
    """Resolve which workspace a briefing request targets.

    Priority:
        1. Explicit ``workspace_id`` query parameter
        2. ``settings_json.morning_card_workspace_id`` on the user
        3. The platform-wide ``General`` workspace

    Raises 404 if step 3 fails (no General workspace exists).
    """
    if workspace_id is not None:
        return workspace_id

    settings = user.get("settings_json") or {}
    pref = settings.get("morning_card_workspace_id")
    if isinstance(pref, int):
        return pref

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id FROM public.bh_workspaces WHERE name = $1",
            _DEFAULT_WORKSPACE_NAME,
        )
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=f"No workspace_id provided and no '{_DEFAULT_WORKSPACE_NAME}' workspace exists",
        )
    return int(row["id"])


def _age_hours(generated_at: datetime) -> float:
    """Hours elapsed between ``generated_at`` and now (UTC). Always >= 0."""
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    delta = now - generated_at
    seconds = delta.total_seconds()
    return seconds / 3600.0 if seconds > 0 else 0.0


async def _fetch_latest_briefing_message(workspace_id: int, user_id: int) -> Optional[dict]:
    """Return the most recent briefing system message for this user+workspace.

    Briefings are stored in user-owned conversations (see
    ``BriefingService.deliver``), so we scope by ``user_id`` to avoid
    surfacing one user's briefing to another user who shares the
    workspace.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT m.id, m.content, m.metadata, m.created_at, m.conversation_id
              FROM public.bh_messages m
              JOIN public.bh_conversations c ON c.id = m.conversation_id
             WHERE c.workspace_id = $1
               AND c.user_id = $2
               AND m.role = 'system'
               AND (
                   m.metadata @> '{"briefing": true}'::jsonb
                OR m.metadata @> '{"type": "briefing"}'::jsonb
               )
             ORDER BY m.created_at DESC
             LIMIT 1
            """,
            workspace_id,
            user_id,
        )
    return dict(row) if row else None


def _build_response(message: dict) -> dict:
    """Shape a briefing message row into the GET/POST response payload."""
    age = _age_hours(message["created_at"])
    return {
        "briefing_id": int(message["id"]),
        "content": message["content"],
        "generated_at": message["created_at"].isoformat(),
        "age_hours": round(age, 2),
        "parsed_sections": parse_sections(message["content"] or ""),
    }


async def _persist_briefing(
    workspace_id: int, user_id: int, content: str
) -> dict:
    """Write a freshly-generated briefing as a system message and return the row.

    Mirrors the conversation-finding behavior of
    ``BriefingService.deliver``: reuse the user's existing
    "Daily Briefing" conversation in the workspace if one exists,
    otherwise create it. The new metadata shape is
    ``{"briefing": true, "type": "briefing"}`` so both the new code path
    here and any legacy reader (e.g. existing dashboards) keep working.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        conv = await conn.fetchrow(
            """
            SELECT id FROM public.bh_conversations
             WHERE workspace_id = $1 AND user_id = $2 AND title = 'Daily Briefing'
               AND is_archived = false
             ORDER BY created_at DESC LIMIT 1
            """,
            workspace_id,
            user_id,
        )
        if conv is None:
            conv = await conn.fetchrow(
                """
                INSERT INTO public.bh_conversations (workspace_id, user_id, title)
                VALUES ($1, $2, 'Daily Briefing') RETURNING id
                """,
                workspace_id,
                user_id,
            )

        message = await conn.fetchrow(
            """
            INSERT INTO public.bh_messages
                (conversation_id, role, content, routing_layer, metadata)
            VALUES ($1, 'system', $2, 'L1', $3::jsonb)
            RETURNING id, content, metadata, created_at, conversation_id
            """,
            conv["id"],
            content,
            json.dumps({"briefing": True, "type": "briefing"}),
        )

        # Bump conversation timestamp so the morning card surfaces at the
        # top of the user's recent-conversations list when they open the
        # workspace.
        await conn.execute(
            "UPDATE public.bh_conversations SET updated_at = now() WHERE id = $1",
            conv["id"],
        )

    return dict(message)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/latest")
async def get_latest_briefing(
    request: Request,
    workspace_id: Optional[int] = Query(default=None),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Return the most recent fresh briefing for the user's morning-card workspace.

    "Fresh" = generated within the last 24 hours (R8.1). Older briefings
    are treated as absent and the response shape becomes
    ``{"briefing_id": null}`` so the frontend can render a generate
    button (R8.3). Missing briefing sections come through as ``"—"``
    placeholders thanks to the shared parser (R8.7).
    """
    target_workspace_id = await _resolve_workspace_id(user, workspace_id)
    await _check_workspace_access(target_workspace_id, user)

    message = await _fetch_latest_briefing_message(target_workspace_id, user["id"])
    if message is None:
        return {"briefing_id": None}

    age = _age_hours(message["created_at"])
    if age > _BRIEFING_FRESH_HOURS:
        return {"briefing_id": None}

    return _build_response(message)


@router.post("/generate-now")
async def generate_briefing_now(
    request: Request,
    workspace_id: Optional[int] = Query(default=None),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Generate a fresh briefing on demand and persist it (R8.4).

    Returns the same shape as ``GET /latest``. Returns 503 if the
    briefing service raises — the frontend already has a sensible
    fallback (keep showing the placeholder, retry later).
    """
    target_workspace_id = await _resolve_workspace_id(user, workspace_id)
    await _check_workspace_access(target_workspace_id, user)

    # Fetch shared services from app state. ``BriefingService`` only needs
    # the model provider, skill executor, and config; we lazily build a
    # SkillExecutor since main.py doesn't keep one on app.state.
    try:
        config = request.app.state.config
        model_provider = request.app.state.model_provider
    except AttributeError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"briefing service unavailable: {exc}",
        )

    from backend.services.skill_executor import SkillExecutor  # local import to avoid cycles

    skill_executor = SkillExecutor(config)
    service = BriefingService(model_provider, skill_executor, config)

    try:
        content = await service.generate(user["id"], target_workspace_id)
    except Exception as exc:
        logger.exception("Briefing generation failed for user %s ws %s", user["id"], target_workspace_id)
        raise HTTPException(
            status_code=503,
            detail=f"briefing service error: {exc}",
        )

    if not content or not content.strip():
        raise HTTPException(
            status_code=503,
            detail="briefing service returned empty content",
        )

    message = await _persist_briefing(target_workspace_id, user["id"], content)
    return _build_response(message)
