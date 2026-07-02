"""Generative UI (Dashboard V2 Task 8): LLM-generated dashboard widgets.

An `render_dashboard_widget` tool call produces a strict widget spec that is
validated here, stored per-user in `bh_dashboard_layouts` under the reserved
`_generated` page, and surfaced by `GET /api/dashboard/generated`. Storing it
per-user (not in the global SSE cache) keeps the dashboard stream's
household-global invariant intact — only a global `layout_epoch` bump rides the
stream, so open dashboards refetch *their own* generated widgets.
"""
import time
from typing import Any

from ..database import get_pool

GENERATED_PAGE = "_generated"
MAX_GENERATED = 3
_TYPES = {"metric", "list", "bar"}


def validate_spec(spec: Any) -> dict:
    """Validate + normalize an LLM widget spec. Raises ValueError on anything
    malformed (the tool turns that into a friendly message, never a crash)."""
    if not isinstance(spec, dict):
        raise ValueError("spec must be an object")
    t = spec.get("type")
    if t not in _TYPES:
        raise ValueError(f"type must be one of {sorted(_TYPES)}")
    title = spec.get("title")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("title is required")
    title = title.strip()[:80]

    if t == "metric":
        value = spec.get("value")
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            raise ValueError("metric requires a 'value'")
        out: dict = {"type": "metric", "title": title, "value": str(value)[:40]}
        if isinstance(spec.get("label"), str):
            out["label"] = spec["label"][:60]
        if isinstance(spec.get("delta"), str):
            out["delta"] = spec["delta"][:40]
        if "delta_positive" in spec:
            out["delta_positive"] = bool(spec["delta_positive"])
        return out

    if t == "list":
        items = spec.get("items")
        if not isinstance(items, list):
            raise ValueError("list requires 'items'")
        clean = [str(i)[:160] for i in items[:20] if isinstance(i, (str, int, float)) and not isinstance(i, bool)]
        if not clean:
            raise ValueError("list needs at least one item")
        return {"type": "list", "title": title, "items": clean}

    # bar
    rows = spec.get("rows")
    if not isinstance(rows, list):
        raise ValueError("bar requires 'rows'")
    clean_rows = [
        {"label": str(r["label"])[:60], "value": float(r["value"])}
        for r in rows[:20]
        if isinstance(r, dict) and isinstance(r.get("label"), str)
        and isinstance(r.get("value"), (int, float)) and not isinstance(r.get("value"), bool)
    ]
    if not clean_rows:
        raise ValueError("bar needs at least one {label, value} row")
    return {"type": "bar", "title": title, "rows": clean_rows}


async def _bump_layout_epoch() -> None:
    """Nudge every open dashboard to refetch its own generated widgets. The epoch
    is not user data, so it's safe on the global stream."""
    from backend.services.dashboard_stream import DashboardStateCache
    cache = DashboardStateCache.get_instance()
    try:
        current = int((await cache.get_all()).get("layout_epoch", 0))
    except (TypeError, ValueError):
        current = 0
    await cache.update("layout_epoch", current + 1)


async def upsert_generated(user_id: int, spec: Any, cap: int = MAX_GENERATED) -> str:
    """Validate + prepend a generated widget to the user's `_generated` page
    (bounded to `cap`, newest first). Returns the new widget id."""
    clean = validate_spec(spec)
    wid = f"gen-{int(time.time() * 1000)}"
    entry = {"id": wid, "spec": clean}
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT widgets FROM public.bh_dashboard_layouts WHERE user_id=$1 AND page_key=$2",
            user_id, GENERATED_PAGE,
        )
        existing = list(row["widgets"]) if row and row["widgets"] else []
        widgets = ([entry] + existing)[:cap]
        await conn.execute(
            """
            INSERT INTO public.bh_dashboard_layouts (user_id, page_key, widgets, updated_at)
            VALUES ($1, $2, $3, now())
            ON CONFLICT (user_id, page_key)
            DO UPDATE SET widgets = EXCLUDED.widgets, updated_at = now()
            """,
            user_id, GENERATED_PAGE, widgets,
        )
    await _bump_layout_epoch()
    return wid


async def list_generated(user_id: int) -> list:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT widgets FROM public.bh_dashboard_layouts WHERE user_id=$1 AND page_key=$2",
            user_id, GENERATED_PAGE,
        )
    return list(row["widgets"]) if row and row["widgets"] else []


async def remove_generated(user_id: int, widget_id: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT widgets FROM public.bh_dashboard_layouts WHERE user_id=$1 AND page_key=$2",
            user_id, GENERATED_PAGE,
        )
        if not row or not row["widgets"]:
            return
        kept = [w for w in row["widgets"] if w.get("id") != widget_id]
        await conn.execute(
            "UPDATE public.bh_dashboard_layouts SET widgets=$3, updated_at=now() WHERE user_id=$1 AND page_key=$2",
            user_id, GENERATED_PAGE, kept,
        )
    await _bump_layout_epoch()
