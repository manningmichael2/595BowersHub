"""
Scheduled Prompts API routes (`/api/scheduled-prompts/*`).

Thin HTTP wrapper over ``backend.services.scheduled_prompts``. The service
owns all the cron validation, workspace-access enforcement, and hook
engine plumbing; this module is responsible only for:

- Mapping FastAPI request bodies / query params into service calls.
- Translating the service's typed exceptions into HTTP responses:
    InvalidPayload / CronInvalid    -> 400
    Forbidden                       -> 403
    NotFound                        -> 404
    ScheduledPromptError (other)    -> 400 (catch-all for service errors)

Authentication is enforced by ``Depends(get_current_user)`` on every
endpoint. Workspace scoping is delegated to the service layer, which
already filters list responses and raises ``Forbidden`` for any
single-row endpoint where the caller lacks access.

Routes:
    GET    /api/scheduled-prompts                  list (?workspace_id=int)
    POST   /api/scheduled-prompts                  create
    PATCH  /api/scheduled-prompts/{id}             update (partial)
    DELETE /api/scheduled-prompts/{id}             delete
    POST   /api/scheduled-prompts/{id}/toggle      enable/disable
    POST   /api/scheduled-prompts/{id}/run-now     immediate execution
    GET    /api/scheduled-prompts/{id}/log         last N log entries

_Requirements: R11.1, R11.2, R11.3, R11.7, R11.8, R11.9, R11.10, R11.11_
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.services import scheduled_prompts as svc

router = APIRouter(prefix="/api/scheduled-prompts", tags=["scheduled-prompts"])


# ---------------------------------------------------------------------------
# Pydantic shapes
# ---------------------------------------------------------------------------


class ScheduledPromptCreate(BaseModel):
    """Body for POST /api/scheduled-prompts."""

    name: str = Field(..., min_length=1, max_length=200)
    workspace_id: int
    prompt_template: str = Field(..., min_length=1)
    cron_expression: str = Field(..., min_length=1)
    delivery_method: str = Field(..., pattern="^(pin|pushover)$")
    description: Optional[str] = None


class ScheduledPromptUpdate(BaseModel):
    """Body for PATCH /api/scheduled-prompts/{id}. All fields optional;
    the service merges only what is set."""

    name: Optional[str] = None
    prompt_template: Optional[str] = None
    cron_expression: Optional[str] = None
    delivery_method: Optional[str] = Field(default=None, pattern="^(pin|pushover)$")
    is_enabled: Optional[bool] = None


class ToggleRequest(BaseModel):
    """Body for POST /api/scheduled-prompts/{id}/toggle."""

    enabled: bool


# ---------------------------------------------------------------------------
# Error translation
# ---------------------------------------------------------------------------


def _raise_http_for_service_error(exc: svc.ScheduledPromptError) -> None:
    """Translate a service exception into the matching HTTPException.

    Order matters: more specific subclasses are checked before the
    generic ``ScheduledPromptError`` base.
    """
    if isinstance(exc, svc.NotFound):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, svc.Forbidden):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, svc.CronInvalid):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "invalid_cron",
                "message": str(exc),
                "expression": exc.expr,
            },
        )
    if isinstance(exc, svc.InvalidPayload):
        raise HTTPException(status_code=400, detail=str(exc))
    # Fallback for any other service-level error.
    raise HTTPException(status_code=400, detail=str(exc))


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def list_scheduled_prompts(
    workspace_id: Optional[int] = Query(default=None),
    user: dict = Depends(get_current_user),
) -> List[dict]:
    """List scheduled prompts visible to the caller.

    With ``workspace_id`` set, results are scoped to that workspace
    (the service raises 403 if the caller cannot access it). Without
    it, results are scoped to every workspace the caller has access
    to (admins see everything).

    _Requirements: R11.1, R11.10_
    """
    try:
        return await svc.list_for_user(user, workspace_id=workspace_id)
    except svc.ScheduledPromptError as e:
        _raise_http_for_service_error(e)


@router.post("")
async def create_scheduled_prompt(
    body: ScheduledPromptCreate,
    user: dict = Depends(get_current_user),
) -> dict:
    """Create a new scheduled prompt (a `bh_hooks` row with
    ``event_type='schedule'`` and ``action_type='call_ai'``).

    The cron expression is validated server-side (R11.11). The caller
    must be able to access the target workspace.

    _Requirements: R11.2, R11.3, R11.11_
    """
    try:
        return await svc.create(user, body.model_dump(exclude_none=True))
    except svc.ScheduledPromptError as e:
        _raise_http_for_service_error(e)


@router.patch("/{hook_id}")
async def update_scheduled_prompt(
    hook_id: int,
    body: ScheduledPromptUpdate,
    user: dict = Depends(get_current_user),
) -> dict:
    """Patch a scheduled prompt. Only the user-facing fields are
    updateable here — workspace and event/action types are immutable
    through this surface.

    _Requirements: R11.7, R11.11_
    """
    partial = body.model_dump(exclude_unset=True)
    if not partial:
        raise HTTPException(status_code=400, detail="No fields to update")
    try:
        return await svc.update(user, hook_id, partial)
    except svc.ScheduledPromptError as e:
        _raise_http_for_service_error(e)


@router.delete("/{hook_id}")
async def delete_scheduled_prompt(
    hook_id: int,
    user: dict = Depends(get_current_user),
) -> dict:
    """Delete a scheduled prompt. Cascading FKs remove the log entries.

    _Requirements: R11.7_
    """
    try:
        await svc.delete(user, hook_id)
    except svc.ScheduledPromptError as e:
        _raise_http_for_service_error(e)
    return {"ok": True}


@router.post("/{hook_id}/toggle")
async def toggle_scheduled_prompt(
    hook_id: int,
    body: ToggleRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """Enable or disable a scheduled prompt without touching the rest
    of its config.

    _Requirements: R11.8_
    """
    try:
        return await svc.toggle(user, hook_id, body.enabled)
    except svc.ScheduledPromptError as e:
        _raise_http_for_service_error(e)


@router.post("/{hook_id}/run-now")
async def run_scheduled_prompt_now(
    hook_id: int,
    request: Request,
    user: dict = Depends(get_current_user),
) -> dict:
    """Execute a scheduled prompt immediately, outside its cron schedule.

    The hook engine is fetched from ``app.state`` so the run goes through
    exactly the same delivery + logging path as a scheduled fire (the
    service writes to ``bh_hook_log``).

    _Requirements: R11.9_
    """
    hook_engine = getattr(request.app.state, "hook_engine", None)
    if hook_engine is None:
        raise HTTPException(
            status_code=503,
            detail="hook engine not initialized",
        )
    try:
        return await svc.run_now(user, hook_id, hook_engine)
    except svc.ScheduledPromptError as e:
        _raise_http_for_service_error(e)


@router.get("/{hook_id}/log")
async def get_scheduled_prompt_log(
    hook_id: int,
    limit: int = Query(default=10, ge=1, le=100),
    user: dict = Depends(get_current_user),
) -> List[dict]:
    """Return the last ``limit`` execution log entries for a scheduled
    prompt, newest first.

    _Requirements: R11.10_
    """
    try:
        return await svc.get_log(user, hook_id, limit=limit)
    except svc.ScheduledPromptError as e:
        _raise_http_for_service_error(e)
