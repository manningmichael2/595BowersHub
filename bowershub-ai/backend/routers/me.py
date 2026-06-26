"""Current-user self-service: the server-computed effective-access payload the
frontend consumes (R5.5 — it never infers permission from role), and the cosmetic
nav self-hide (R5.4 — hiding a button NEVER restricts the route)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from backend.database import get_pool
from backend.middleware.auth import get_current_user
from backend.services import authz

router = APIRouter(prefix="/api/me", tags=["me"])


class NavHideRequest(BaseModel):
    model_config = {"extra": "forbid"}
    hidden: list[str]


@router.get("/features")
async def my_features(user: dict = Depends(get_current_user)) -> dict:
    """Effective access for the current user: role, resolved capabilities, the
    feature list with per-feature `permitted` (server-authoritative), and the
    user's cosmetic `hidden_nav` so the frontend computes nav from one payload."""
    access = authz.effective_access(user)
    settings = user.get("settings_json") or {}
    access["hidden_nav"] = settings.get("hidden_nav", [])
    return access


@router.put("/settings/nav")
async def set_hidden_nav(body: NavHideRequest, user: dict = Depends(get_current_user)) -> dict:
    """Cosmetic self-hide (R5.4). Stores `settings_json.hidden_nav`. This NEVER
    403s and NEVER affects route access — only which nav buttons the user sees.
    Validated to permitted features only (you can't 'hide' what you can't see)."""
    access = authz.effective_access(user)
    permitted = {f["key"] for f in access["features"] if f["permitted"]}
    hidden = [k for k in body.hidden if k in permitted]

    pool = get_pool()
    async with pool.acquire() as conn:
        current = await conn.fetchval(
            "SELECT settings_json FROM public.bh_users WHERE id = $1", user["id"])
        settings = dict(current or {})
        settings["hidden_nav"] = hidden
        await conn.execute(
            "UPDATE public.bh_users SET settings_json = $1 WHERE id = $2", settings, user["id"])
    return {"hidden_nav": hidden}
