"""Current-user self-service: the server-computed effective-access payload the
frontend consumes (R5.5 — it never infers permission from role), and the cosmetic
nav self-hide (R5.4 — hiding a button NEVER restricts the route)."""

from __future__ import annotations

import json
import re
from datetime import time as dt_time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator

from backend.database import get_pool
from backend.middleware.auth import get_current_user
from backend.services import authz

router = APIRouter(prefix="/api/me", tags=["me"])

# Global notification preferences are stored under this synthetic event_type so
# the user has one set of channel + quiet-hour settings; the NotificationService
# falls back to this row when no event-specific row exists.
DEFAULT_EVENT_TYPE = "default"

_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class NavHideRequest(BaseModel):
    model_config = {"extra": "forbid"}
    hidden: list[str]


class NotificationPrefs(BaseModel):
    """Per-user global notification preferences. Quiet hours are 'HH:MM' 24h
    strings (or null for none)."""
    model_config = {"extra": "forbid"}
    web_push: bool = True
    pushover: bool = False
    quiet_start: Optional[str] = None
    quiet_end: Optional[str] = None

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def _valid_hhmm(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if not _HHMM.match(v):
            raise ValueError("quiet hours must be 'HH:MM' (24-hour)")
        return v


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


# ---- Notification preferences --------------------------------------------

def _fmt_time(t: Optional[dt_time]) -> Optional[str]:
    """Render a DB `time` as 'HH:MM' (or None)."""
    return t.strftime("%H:%M") if t is not None else None


def _parse_time(s: Optional[str]) -> Optional[dt_time]:
    """Parse an 'HH:MM' string into a `time` (or None). Input is pre-validated."""
    if not s:
        return None
    hh, mm = s.split(":")
    return dt_time(int(hh), int(mm))


@router.get("/notifications")
async def get_notification_prefs(
    request: Request, user: dict = Depends(get_current_user)
) -> dict:
    """The user's global notification preferences plus which channels the server
    can actually deliver (web push / Pushover need server-side config). The UI
    greys out a channel that isn't available."""
    config = request.app.state.config
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT web_push, pushover, quiet_start, quiet_end
              FROM public.bh_notification_prefs
             WHERE user_id = $1 AND event_type = $2
            """,
            user["id"], DEFAULT_EVENT_TYPE,
        )
    prefs = (
        {
            "web_push": row["web_push"],
            "pushover": row["pushover"],
            "quiet_start": _fmt_time(row["quiet_start"]),
            "quiet_end": _fmt_time(row["quiet_end"]),
        }
        if row
        else {"web_push": True, "pushover": False, "quiet_start": None, "quiet_end": None}
    )
    return {
        "prefs": prefs,
        "available": {
            "web_push": config.webpush_enabled,
            "pushover": config.pushover_enabled,
        },
    }


@router.put("/notifications")
async def set_notification_prefs(
    body: NotificationPrefs, user: dict = Depends(get_current_user)
) -> dict:
    """Upsert the user's global notification preferences (the `default` row)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.bh_notification_prefs
                   (user_id, event_type, web_push, pushover, quiet_start, quiet_end)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (user_id, event_type) DO UPDATE SET
                web_push   = EXCLUDED.web_push,
                pushover   = EXCLUDED.pushover,
                quiet_start = EXCLUDED.quiet_start,
                quiet_end  = EXCLUDED.quiet_end
            """,
            user["id"], DEFAULT_EVENT_TYPE,
            body.web_push, body.pushover,
            _parse_time(body.quiet_start), _parse_time(body.quiet_end),
        )
    return {
        "prefs": {
            "web_push": body.web_push,
            "pushover": body.pushover,
            "quiet_start": body.quiet_start or None,
            "quiet_end": body.quiet_end or None,
        }
    }


# ---- Web Push subscriptions ----------------------------------------------
#
# The Notifications "web push" preference is the user's intent; it only delivers
# if THIS browser has registered a Push subscription. These endpoints carry the
# subscribe/unsubscribe handshake the frontend performs when the toggle flips.

class PushSubscriptionIn(BaseModel):
    # The browser PushSubscription JSON: { endpoint, expirationTime, keys }.
    # `extra="allow"` keeps `keys`/`expirationTime` so pywebpush can sign for it.
    model_config = {"extra": "allow"}
    endpoint: str


class PushUnsubscribeIn(BaseModel):
    model_config = {"extra": "forbid"}
    endpoint: str


@router.get("/push/key")
async def get_push_key(request: Request, user: dict = Depends(get_current_user)) -> dict:
    """The VAPID public key the browser needs to create a push subscription, plus
    whether web push is configured server-side at all."""
    config = request.app.state.config
    return {
        "enabled": config.webpush_enabled,
        "public_key": config.VAPID_PUBLIC_KEY if config.webpush_enabled else None,
    }


@router.post("/push/subscribe")
async def push_subscribe(
    body: PushSubscriptionIn, request: Request, user: dict = Depends(get_current_user)
) -> dict:
    """Register this browser's push subscription. Idempotent per endpoint: a
    re-subscribe (same endpoint) replaces the prior row rather than duplicating."""
    config = request.app.state.config
    if not config.webpush_enabled:
        raise HTTPException(status_code=503, detail="Web push is not configured on this server.")

    subscription = body.model_dump()
    user_agent = request.headers.get("user-agent", "")
    pool = get_pool()
    async with pool.acquire() as conn:
        # Dedupe by endpoint (no unique constraint on the table) so repeat
        # subscriptions from the same device don't pile up.
        await conn.execute(
            "DELETE FROM public.bh_push_subscriptions "
            "WHERE user_id = $1 AND subscription->>'endpoint' = $2",
            user["id"], body.endpoint,
        )
        await conn.execute(
            "INSERT INTO public.bh_push_subscriptions (user_id, subscription, user_agent) "
            "VALUES ($1, $2::jsonb, $3)",
            user["id"], json.dumps(subscription), user_agent,
        )
    return {"ok": True}


@router.post("/push/unsubscribe")
async def push_unsubscribe(
    body: PushUnsubscribeIn, user: dict = Depends(get_current_user)
) -> dict:
    """Remove this browser's push subscription (the user turned web push off, or
    the browser revoked it)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM public.bh_push_subscriptions "
            "WHERE user_id = $1 AND subscription->>'endpoint' = $2",
            user["id"], body.endpoint,
        )
    return {"ok": True}
