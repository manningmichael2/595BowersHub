"""
List configuration — DB-driven types, stores, aisle layouts, and routing config.

Everything user-facing here is a DB row (NO-HARDCODING): list types, stores, the
store→aisle order, the routing thresholds, and the elected default list. The
frontend reads these via the API and never hardcodes options.
"""
from __future__ import annotations

import json
from typing import Optional

from backend.database import get_pool
from backend.services.lists import ListError


# ── List types ───────────────────────────────────────────────────────────────

async def list_types() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, label, icon, description, group_by, default_sort, "
            "       default_order, category_set, is_active "
            "FROM public.bh_list_types WHERE is_active ORDER BY sort_order, label")
    return [dict(r) for r in rows]


# ── Stores + aisle layouts ───────────────────────────────────────────────────

async def list_stores() -> list[dict]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, name, is_active, sort_order FROM public.bh_stores "
            "WHERE is_active ORDER BY sort_order, LOWER(name)")
    return [dict(r) for r in rows]


async def create_store(name: str, user_id: int) -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            row = await conn.fetchrow(
                "INSERT INTO public.bh_stores (name, created_by) VALUES ($1,$2) "
                "RETURNING id, name, is_active, sort_order", name.strip(), user_id)
        except Exception as e:
            if "uq_stores_name" in str(e):
                raise ListError(f"A store named '{name.strip()}' already exists.") from e
            raise
    return dict(row)


async def update_store(store_id: int, *, name: Optional[str] = None,
                       sort_order: Optional[int] = None, is_active: Optional[bool] = None) -> bool:
    sets, args = [], []
    if name is not None:
        args.append(name.strip()); sets.append(f"name=${len(args)}")
    if sort_order is not None:
        args.append(sort_order); sets.append(f"sort_order=${len(args)}")
    if is_active is not None:
        args.append(is_active); sets.append(f"is_active=${len(args)}")
    if not sets:
        return False
    args.append(store_id)
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE public.bh_stores SET {', '.join(sets)}, updated_at=now() "
            f"WHERE id=${len(args)}", *args)
    return result.endswith("1")


async def delete_store(store_id: int) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute("DELETE FROM public.bh_stores WHERE id=$1", store_id)
    return result.endswith("1")


async def set_store_aisles(store_id: int, departments: list[str]) -> bool:
    """Replace a store's ordered department (aisle) layout."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await conn.fetchval("SELECT 1 FROM public.bh_stores WHERE id=$1", store_id):
            return False
        async with conn.transaction():
            await conn.execute("DELETE FROM public.bh_store_aisles WHERE store_id=$1", store_id)
            for idx, dept in enumerate(departments, start=1):
                await conn.execute(
                    "INSERT INTO public.bh_store_aisles (store_id, department, sort_order) "
                    "VALUES ($1,$2,$3)", store_id, dept, idx)
    return True


async def store_aisle_order(conn, store_name: str) -> Optional[list[str]]:
    """Ordered departments for a store name (None if no layout)."""
    rows = await conn.fetch(
        "SELECT a.department FROM public.bh_store_aisles a JOIN public.bh_stores s ON s.id=a.store_id "
        "WHERE LOWER(s.name)=LOWER($1) ORDER BY a.sort_order", store_name)
    return [r["department"] for r in rows] or None


# ── Routing config + default list ────────────────────────────────────────────

async def routing_config(conn) -> dict:
    val = await conn.fetchval(
        "SELECT value_json FROM public.bh_platform_settings WHERE key='lists.routing'")
    return val or {"match_threshold": 0.40, "create_threshold": 0.35, "ambiguity_margin": 0.04}


async def get_default_list_id(conn) -> Optional[int]:
    return await conn.fetchval(
        "SELECT value_json FROM public.bh_platform_settings WHERE key='lists.default_list_id'")


async def set_default_list_id(conn, list_id: int) -> None:
    await conn.execute(
        "INSERT INTO public.bh_platform_settings (key, value_json) VALUES ('lists.default_list_id',$1::jsonb) "
        "ON CONFLICT (key) DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=now()",
        json.dumps(list_id))


async def config() -> dict:
    """UI config bundle: sort options + routing knobs + default list."""
    pool = get_pool()
    async with pool.acquire() as conn:
        routing = await routing_config(conn)
        default = await get_default_list_id(conn)
    return {
        "sorts": [
            {"key": "manual", "label": "Manual"},
            {"key": "name", "label": "Name"},
            {"key": "due", "label": "Due date"},
            {"key": "recent", "label": "Recently added"},
            {"key": "checked", "label": "Checked"},
        ],
        "routing": routing,
        "default_list_id": default,
    }
