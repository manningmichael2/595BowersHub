"""
Client error telemetry — proactive error visibility.

POST /api/telemetry/client-error  (auth)   Store a browser-reported error and,
    the first time a given signature is seen within a rolling window, ping the
    admin via Pushover (rate-limited so an error loop can't spam).
GET  /api/telemetry/client-errors (admin)  Recent errors for review.

Errors are also browsable directly in the DB browser (public.bh_client_errors).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from backend.database import get_pool
from backend.middleware.auth import get_current_user, require_admin
from backend.services import pushover

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# Per-signature Pushover cooldown: alert at most once per window per distinct
# error, so a repeating crash pings once an hour rather than continuously.
ALERT_WINDOW_MINUTES = 60


class ClientErrorIn(BaseModel):
    message: str
    stack: Optional[str] = None
    url: Optional[str] = None


def _signature(message: str, stack: Optional[str]) -> str:
    """Stable dedupe key: message + the first real stack frame."""
    first_frame = ""
    if stack:
        lines = [ln.strip() for ln in stack.splitlines() if ln.strip()]
        if len(lines) > 1:
            first_frame = lines[1]
    return hashlib.sha256(f"{message}::{first_frame}".encode("utf-8")).hexdigest()[:16]


@router.post("/client-error")
async def report_client_error(
    body: ClientErrorIn,
    request: Request,
    user: dict = Depends(get_current_user),
):
    message = (body.message or "").strip()[:2000]
    if not message:
        return {"ok": True}

    stack = body.stack[:8000] if body.stack else None
    url = body.url[:1000] if body.url else None
    user_agent = request.headers.get("user-agent", "")[:500]
    sig = _signature(message, stack)

    pool = get_pool()
    async with pool.acquire() as conn:
        # Has this signature been recorded inside the cooldown window already?
        recent = await conn.fetchval(
            """
            SELECT 1 FROM public.bh_client_errors
            WHERE signature = $1
              AND created_at > now() - make_interval(mins => $2)
            LIMIT 1
            """,
            sig,
            ALERT_WINDOW_MINUTES,
        )
        await conn.execute(
            """
            INSERT INTO public.bh_client_errors
                (user_id, message, stack, url, user_agent, signature)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            user["id"],
            message,
            stack,
            url,
            user_agent,
            sig,
        )

    # First sighting in the window → ping the admin. Best-effort; a failed
    # notification must not fail the report.
    if not recent:
        try:
            await pushover.send_notification(
                title="⚠️ BowersHub client error",
                message=message[:900],
                priority=0,
                url=url,
                url_title="Open page" if url else None,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("client-error Pushover ping failed: %s", e)

    return {"ok": True}


@router.get("/client-errors")
async def list_client_errors(
    limit: int = Query(50, ge=1, le=500),
    _admin: dict = Depends(require_admin),
):
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, message, stack, url, user_agent, signature, created_at
            FROM public.bh_client_errors
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return {"errors": [dict(r) for r in rows]}
