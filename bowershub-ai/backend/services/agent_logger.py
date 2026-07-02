"""Agent/system event log for the Dashboard V2 Task Reel + Action Center.

`log_event()` persists a row to `bh_agent_events` and pushes it onto the live
SSE cache so connected dashboards see it immediately. Events are household-global
system activity (background jobs, syncs, alerts) — consistent with the dashboard
stream's global-cache model (see `dashboard_stream._SYSTEM_CTX`).

Logging is fire-and-forget: a background job reporting its own progress must
never fail because the event log is momentarily unavailable.
"""
import logging
from datetime import datetime
from typing import Any, Optional

from ..database import get_pool
from .dashboard_stream import DashboardStateCache

logger = logging.getLogger(__name__)

AGENT_EVENTS_KEY = "agent_events"
MAX_EVENTS = 50
_VALID_LEVELS = {"info", "success", "warning", "error"}


def _to_event(row) -> dict[str, Any]:
    """Row → JSON-serializable event. `created_at` MUST be a string: the SSE
    route serializes the whole cache with `json.dumps`, which can't encode a
    datetime. `action_payload` is already a dict (the pool's jsonb decoder)."""
    created = row["created_at"]
    return {
        "id": row["id"],
        "created_at": created.isoformat() if isinstance(created, datetime) else created,
        "source": row["source"],
        "message": row["message"],
        "level": row["level"],
        "action_payload": row["action_payload"],
    }


async def log_event(
    source: str,
    message: str,
    level: str = "info",
    action_payload: Optional[dict[str, Any]] = None,
) -> None:
    """Persist an agent event and push it onto the live dashboard stream."""
    if level not in _VALID_LEVELS:
        level = "info"
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO public.bh_agent_events (source, message, level, action_payload)
                VALUES ($1, $2, $3, $4)
                RETURNING id, created_at, source, message, level, action_payload
                """,
                source, message, level, action_payload,
            )
        await DashboardStateCache.get_instance().append_event(_to_event(row), cap=MAX_EVENTS)
    except Exception:
        logger.exception("Failed to log agent event (source=%s)", source)


async def hydrate_recent(limit: int = MAX_EVENTS) -> None:
    """Seed the SSE cache with recent events so a fresh dashboard connection's
    first frame shows history rather than an empty reel."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, created_at, source, message, level, action_payload
                  FROM public.bh_agent_events
                 ORDER BY created_at DESC, id DESC
                 LIMIT $1
                """,
                limit,
            )
        await DashboardStateCache.get_instance().update(AGENT_EVENTS_KEY, [_to_event(r) for r in rows])
    except Exception:
        logger.exception("Failed to hydrate agent events")
