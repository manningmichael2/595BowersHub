"""
Lists Service — shopping lists, to-do lists, packing lists, etc.

Items can be added, checked off, unchecked, and removed via chat or DB Admin.
Lists are household-shared by default (is_shared) — both members add to and check
off one list — while a list can still be private to its creator (is_shared=false).
Resolution prefers the shared list of a given name (see `_resolve_list_id`).
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.database import get_pool
from backend.services import list_schema

logger = logging.getLogger(__name__)

_SORT_GAP = 1000.0          # spacing between sort_order values
_SORT_EPSILON = 1e-6        # below this gap between neighbours, rebalance first


class ListError(Exception):
    """A list operation failed in a way the caller should surface (e.g. 404/409)."""


def _coerce_due(val):
    """ISO date/datetime string → datetime for the timestamptz column (asyncpg
    binds Python datetimes, not strings). Already-datetime values pass through."""
    if val is None or isinstance(val, datetime):
        return val
    return datetime.fromisoformat(str(val).replace("Z", "+00:00"))


async def resolve_only(conn, list_name: str, user_id: int) -> Optional[int]:
    """Resolve an EXISTING list the user may access (shared of that name, or the
    user's own private), preferring shared. Never creates — this is the path the
    AI router uses so a misheard name can't spawn a junk list (R4.3)."""
    return await conn.fetchval(
        "SELECT id FROM public.bh_lists "
        "WHERE LOWER(name) = LOWER($1) AND (is_shared OR user_id = $2) AND is_archived = false "
        "ORDER BY is_shared DESC, id LIMIT 1",
        list_name.strip(), user_id,
    )


async def create_list(conn, name: str, user_id: int,
                      list_type_id: Optional[int] = None, is_shared: bool = True) -> int:
    """Explicitly create a list (the only create path). Defaults to the 'simple'
    type. Raises ListError on a name collision under the household rules."""
    if list_type_id is None:
        list_type_id = await conn.fetchval(
            "SELECT id FROM public.bh_list_types WHERE name = 'simple'")
    try:
        return await conn.fetchval(
            "INSERT INTO public.bh_lists (name, user_id, list_type_id, is_shared) "
            "VALUES ($1, $2, $3, $4) RETURNING id",
            name.strip(), user_id, list_type_id, is_shared,
        )
    except Exception as e:  # asyncpg.UniqueViolationError on the partial indexes
        if "uq_lists_shared_name" in str(e) or "uq_lists_private_name" in str(e):
            raise ListError(f"A list named '{name.strip()}' already exists.") from e
        raise


async def _resolve_list_id(conn, list_name: str, user_id: int, create: bool = False) -> Optional[int]:
    """Back-compat resolver used by the name-addressed chat/REST shims. Delegates
    to resolve_only / create_list. The REST UI shim still creates-on-add; the AI
    path calls resolve_only directly (no create)."""
    list_id = await resolve_only(conn, list_name, user_id)
    if list_id is not None:
        return list_id
    if create:
        return await create_list(conn, list_name, user_id)
    return None


async def _list_accessible(conn, list_id: int, user_id: int) -> bool:
    """True if the list exists and the user may access it (shared or own)."""
    return bool(await conn.fetchval(
        "SELECT 1 FROM public.bh_lists WHERE id = $1 AND (is_shared OR user_id = $2)",
        list_id, user_id,
    ))


async def get_list(list_name: str, user_id: int = 1, show_checked: bool = False) -> dict:
    """
    Get all items on a list.
    By default only shows unchecked (active) items.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await _resolve_list_id(conn, list_name, user_id)
        if not list_id:
            return {
                "list": list_name,
                "items": [],
                "_display": f"📋 **{list_name.title()}** list is empty (or doesn't exist yet). Add items with: *add X to my {list_name} list*",
            }

        # Get items
        if show_checked:
            items = await conn.fetch(
                "SELECT * FROM public.bh_list_items WHERE list_id = $1 ORDER BY checked, created_at",
                list_id
            )
        else:
            items = await conn.fetch(
                "SELECT * FROM public.bh_list_items WHERE list_id = $1 AND checked = false ORDER BY created_at",
                list_id
            )

    items_list = [dict(r) for r in items]
    display = _format_list(list_name, items_list, show_checked)

    return {
        "list": list_name,
        "count": len(items_list),
        "items": [{"text": i["text"], "quantity": i.get("quantity"), "checked": i["checked"]} for i in items_list],
        "_display": display,
    }


async def add_items(list_name: str, items: list[str], user_id: int = 1) -> dict:
    """
    Add one or more items to a list. Creates the list if it doesn't exist.
    """
    if not items:
        return {"_display": "No items to add."}

    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await _resolve_list_id(conn, list_name, user_id, create=True)

        # Add items (skip duplicates)
        added = []
        for item_text in items:
            item_text = item_text.strip()
            if not item_text:
                continue
            # Parse quantity if present (e.g., "2 lbs chicken" → quantity="2 lbs", text="chicken")
            quantity, text = _parse_quantity(item_text)

            # Check for existing unchecked duplicate
            existing = await conn.fetchval(
                "SELECT id FROM public.bh_list_items WHERE list_id = $1 AND LOWER(text) = LOWER($2) AND checked = false",
                list_id, text
            )
            if existing:
                continue  # Already on the list

            await conn.execute(
                "INSERT INTO public.bh_list_items (list_id, text, quantity) VALUES ($1, $2, $3)",
                list_id, text, quantity
            )
            added.append(item_text)

        # Update list timestamp
        await conn.execute(
            "UPDATE public.bh_lists SET updated_at = NOW() WHERE id = $1", list_id
        )

    if not added:
        return {"_display": f"Those items are already on your **{list_name}** list."}

    items_str = ", ".join(f"**{a}**" for a in added)
    return {
        "added": added,
        "count": len(added),
        "_display": f"✅ Added to **{list_name}**: {items_str}",
    }


async def check_items(list_name: str, items: list[str], user_id: int = 1) -> dict:
    """
    Check off (mark as done/purchased) items on a list.
    Matches by fuzzy substring — "milk" matches "whole milk".
    """
    if not items:
        return {"_display": "No items to check off."}

    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await _resolve_list_id(conn, list_name, user_id)
        if not list_id:
            return {"_display": f"No list named **{list_name}** found."}

        checked = []
        for item_text in items:
            item_text = item_text.strip().lower()
            if not item_text:
                continue
            # Fuzzy match: check items where text contains the search term
            result = await conn.execute("""
                UPDATE public.bh_list_items
                SET checked = true, checked_at = NOW()
                WHERE list_id = $1 AND checked = false AND LOWER(text) LIKE '%' || $2 || '%'
            """, list_id, item_text)
            # Check if any rows were affected
            count = int(result.split(" ")[-1]) if result else 0
            if count > 0:
                checked.append(item_text)

    if not checked:
        return {"_display": f"Couldn't find those items on your **{list_name}** list."}

    items_str = ", ".join(f"~~{c}~~" for c in checked)
    return {
        "checked": checked,
        "_display": f"✓ Checked off: {items_str}",
    }


async def remove_items(list_name: str, items: list[str], user_id: int = 1) -> dict:
    """Remove items from a list entirely (not just check off)."""
    if not items:
        return {"_display": "No items to remove."}

    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await _resolve_list_id(conn, list_name, user_id)
        if not list_id:
            return {"_display": f"No list named **{list_name}** found."}

        removed = []
        for item_text in items:
            item_text = item_text.strip().lower()
            result = await conn.execute("""
                DELETE FROM public.bh_list_items
                WHERE list_id = $1 AND LOWER(text) LIKE '%' || $2 || '%'
            """, list_id, item_text)
            count = int(result.split(" ")[-1]) if result else 0
            if count > 0:
                removed.append(item_text)

    if not removed:
        return {"_display": f"Couldn't find those items on your **{list_name}** list."}

    return {"removed": removed, "_display": f"🗑️ Removed: {', '.join(removed)}"}


async def clear_checked(list_name: str, user_id: int = 1) -> dict:
    """Remove all checked items from a list (clean up after shopping trip)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await _resolve_list_id(conn, list_name, user_id)
        if not list_id:
            return {"_display": f"No list named **{list_name}** found."}

        result = await conn.execute(
            "DELETE FROM public.bh_list_items WHERE list_id = $1 AND checked = true",
            list_id
        )
        count = int(result.split(" ")[-1]) if result else 0

    return {"_display": f"🧹 Cleared {count} checked item(s) from **{list_name}**."}


async def get_all_lists(user_id: int = 1, archived: bool = False) -> dict:
    """Get all lists the user can see (household-shared + their own private) with
    item counts. By default only active lists; ``archived=True`` returns the
    archived ones (for the 'show archived / unarchive' UI)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT l.id, l.name, l.description, l.list_type_id,
                   t.name AS type, t.icon AS icon,
                   COUNT(i.id) FILTER (WHERE i.checked = false) as pending,
                   COUNT(i.id) FILTER (WHERE i.checked = true) as done
            FROM public.bh_lists l
            LEFT JOIN public.bh_list_types t ON t.id = l.list_type_id
            LEFT JOIN public.bh_list_items i ON i.list_id = l.id
            WHERE (l.is_shared OR l.user_id = $1) AND l.is_archived = $2
            GROUP BY l.id, l.name, l.description, l.list_type_id, t.name, t.icon
            ORDER BY l.updated_at DESC
        """, user_id, archived)

    if not rows:
        return {"lists": [], "_display": "You don't have any lists yet. Try: *add milk to my shopping list*"}

    lines = ["## 📋 Your Lists", ""]
    for r in rows:
        pending = r["pending"]
        done = r["done"]
        lines.append(f"- **{r['name']}** — {pending} item{'s' if pending != 1 else ''}{f' (+{done} checked)' if done else ''}")
    return {"lists": [dict(r) for r in rows], "_display": "\n".join(lines)}


# ---- ID-based operations (for the UI; the chat path above is text/fuzzy) ------

async def get_items(list_name: str, user_id: int = 1) -> dict:
    """Full item list WITH ids (checked + unchecked), for the UI. Creates nothing."""
    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await _resolve_list_id(conn, list_name, user_id)
        if not list_id:
            return {"list": list_name, "items": []}
        rows = await conn.fetch(
            "SELECT id, text, quantity, checked, added_by FROM public.bh_list_items "
            "WHERE list_id = $1 ORDER BY checked, created_at",
            list_id,
        )
    return {"list": list_name, "items": [dict(r) for r in rows]}


async def _item_accessible(conn, item_id: int, user_id: int) -> Optional[int]:
    """Return the item id if it lives on a list the user may access, else None."""
    return await conn.fetchval(
        "SELECT i.id FROM public.bh_list_items i JOIN public.bh_lists l ON l.id = i.list_id "
        "WHERE i.id = $1 AND (l.is_shared OR l.user_id = $2)",
        item_id, user_id,
    )


async def set_checked(item_id: int, checked: bool, user_id: int = 1) -> bool:
    """Check/uncheck a single item by id. Returns False if not accessible."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _item_accessible(conn, item_id, user_id):
            return False
        await conn.execute(
            "UPDATE public.bh_list_items SET checked = $2, "
            "checked_at = CASE WHEN $2 THEN NOW() ELSE NULL END WHERE id = $1",
            item_id, checked,
        )
    return True


async def update_item(item_id: int, changes: dict, user_id: int = 1) -> bool:
    """Update an item's fields by id (checked/text/category/due_date/assignee +
    JSONB attributes), validated against the list's effective schema. LWW; returns
    False if inaccessible, raises ListSchemaError on a bad value."""
    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await conn.fetchval(
            "SELECT i.list_id FROM public.bh_list_items i JOIN public.bh_lists l ON l.id = i.list_id "
            "WHERE i.id = $1 AND (l.is_shared OR l.user_id = $2)", item_id, user_id)
        if list_id is None:
            return False
        changes = dict(changes)
        sort_order = changes.pop("sort_order", None)
        checked = changes.pop("checked", None)
        schema = await list_schema.resolve_schema(conn, list_id)
        nested = changes.pop("attributes", None) or {}
        field_values = {k: v for k, v in {**changes, **nested}.items() if k != "attributes"}
        cols, attrs = list_schema.partition_item_values(schema, field_values)
        sets, args = [], []
        for col, val in cols.items():
            args.append(_coerce_due(val) if col == "due_date" else val)
            sets.append(f"{col} = ${len(args)}")
        if attrs:
            args.append(json.dumps(attrs)); sets.append(f"attributes = attributes || ${len(args)}::jsonb")
        if sort_order is not None:
            args.append(sort_order); sets.append(f"sort_order = ${len(args)}")
        if checked is not None:
            args.append(checked)
            sets.append(f"checked = ${len(args)}")
            sets.append(f"checked_at = CASE WHEN ${len(args)} THEN NOW() ELSE NULL END")
        if not sets:
            return True
        args.append(item_id)
        await conn.execute(
            f"UPDATE public.bh_list_items SET {', '.join(sets)} WHERE id = ${len(args)}", *args)
    return True


async def delete_item(item_id: int, user_id: int = 1) -> bool:
    """Delete a single item by id. Returns False if not accessible."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _item_accessible(conn, item_id, user_id):
            return False
        await conn.execute("DELETE FROM public.bh_list_items WHERE id = $1", item_id)
    return True


# ---- ID-addressed v2 operations (schema-validated, no auto-create) ----------

async def get_items_by_id(list_id: int, user_id: int = 1) -> Optional[dict]:
    """Full item list with ids + v2 fields for a list, by id. None if inaccessible."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            return None
        rows = await conn.fetch(
            "SELECT id, text, quantity, checked, added_by, category, due_date, "
            "       assignee_user_id, sort_order, attributes "
            "FROM public.bh_list_items WHERE list_id = $1 "
            "ORDER BY checked, sort_order NULLS LAST, id",
            list_id,
        )
    return {"list_id": list_id, "items": [dict(r) for r in rows]}


async def add_items_by_id(list_id: int, items: list, user_id: int = 1) -> dict:
    """Add items to a list BY ID — no name resolution, no auto-create (R4.3).
    Each item may be a plain string or a dict {text, quantity?, category?,
    due_date?, assignee_user_id?, attributes?}. Values are validated/partitioned
    against the list's effective schema (R1.5)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            raise ListError("List not found")
        schema = await list_schema.resolve_schema(conn, list_id)
        # For a list that groups by category (grocery), auto-assign a department
        # to items added without one (R5.5).
        from backend.services import list_grouping
        ltype = await conn.fetchrow(
            "SELECT t.id, t.group_by FROM public.bh_lists l "
            "JOIN public.bh_list_types t ON t.id = l.list_type_id WHERE l.id = $1", list_id)
        autocat = ltype is not None and ltype["group_by"] == "category"
        next_so = await conn.fetchval(
            "SELECT COALESCE(MAX(sort_order), 0) FROM public.bh_list_items WHERE list_id = $1",
            list_id,
        )
        added = []
        for raw in items:
            spec = {"text": raw} if isinstance(raw, str) else dict(raw)
            text = str(spec.pop("text", "")).strip()
            if not text:
                continue
            quantity = spec.pop("quantity", None)
            if quantity is None:
                quantity, text = _parse_quantity(text)
            # Skip an existing unchecked duplicate (same insert-time semantics).
            if await conn.fetchval(
                "SELECT 1 FROM public.bh_list_items "
                "WHERE list_id = $1 AND LOWER(text) = LOWER($2) AND checked = false",
                list_id, text,
            ):
                continue
            # Field values may arrive as top-level core fields (category, due_date,
            # assignee_user_id) AND/OR a nested `attributes` dict for the JSONB tail.
            nested = spec.pop("attributes", None) or {}
            field_values = {k: v for k, v in {**spec, **nested}.items() if v is not None}
            cols, attrs = list_schema.partition_item_values(schema, field_values)
            if autocat and not cols.get("category"):
                try:
                    dept = await list_grouping.categorize(conn, ltype["id"], text)
                    if dept:
                        cols["category"] = dept
                except Exception:  # auto-cat is best-effort — never block an add (R4.5)
                    logger.debug("auto-categorize failed for %r", text, exc_info=True)
            next_so += _SORT_GAP
            await conn.execute(
                "INSERT INTO public.bh_list_items "
                "(list_id, text, quantity, sort_order, category, due_date, assignee_user_id, attributes) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb)",
                list_id, text, quantity, next_so,
                cols.get("category"), _coerce_due(cols.get("due_date")),
                cols.get("assignee_user_id"),
                json.dumps(attrs),
            )
            added.append(text)
        await conn.execute("UPDATE public.bh_lists SET updated_at = NOW() WHERE id = $1", list_id)
    return {"added": added, "count": len(added)}


async def clear_checked_by_id(list_id: int, user_id: int = 1) -> int:
    """Remove all checked items from a list by id. Returns count removed (-1 if inaccessible)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            return -1
        result = await conn.execute(
            "DELETE FROM public.bh_list_items WHERE list_id = $1 AND checked = true", list_id)
        return int(result.split(" ")[-1]) if result else 0


async def _rebalance(conn, list_id: int) -> None:
    """Re-space a list's sort_order to clean multiples of the gap, preserving order."""
    rows = await conn.fetch(
        "SELECT id FROM public.bh_list_items WHERE list_id = $1 "
        "ORDER BY sort_order NULLS LAST, id", list_id)
    for idx, r in enumerate(rows, start=1):
        await conn.execute(
            "UPDATE public.bh_list_items SET sort_order = $2 WHERE id = $1",
            r["id"], idx * _SORT_GAP)


async def move_item(item_id: int, before_id: Optional[int], after_id: Optional[int],
                    user_id: int = 1) -> bool:
    """Place item between the items before_id and after_id (either may be None for
    an end). Writes the midpoint sort_order; rebalances first if the gap underflows
    (R3.4). Returns False if inaccessible."""
    pool = get_pool()
    async with pool.acquire() as conn:
        list_id = await conn.fetchval(
            "SELECT i.list_id FROM public.bh_list_items i JOIN public.bh_lists l ON l.id = i.list_id "
            "WHERE i.id = $1 AND (l.is_shared OR l.user_id = $2)", item_id, user_id)
        if list_id is None:
            return False
        async with conn.transaction():
            prev_so = await conn.fetchval(
                "SELECT sort_order FROM public.bh_list_items WHERE id = $1 AND list_id = $2",
                before_id, list_id) if before_id else None
            next_so = await conn.fetchval(
                "SELECT sort_order FROM public.bh_list_items WHERE id = $1 AND list_id = $2",
                after_id, list_id) if after_id else None
            if prev_so is not None and next_so is not None and (next_so - prev_so) < _SORT_EPSILON:
                await _rebalance(conn, list_id)
                prev_so = await conn.fetchval(
                    "SELECT sort_order FROM public.bh_list_items WHERE id = $1", before_id)
                next_so = await conn.fetchval(
                    "SELECT sort_order FROM public.bh_list_items WHERE id = $1", after_id)
            if prev_so is None and next_so is None:
                new_so = _SORT_GAP
            elif prev_so is None:
                new_so = next_so - _SORT_GAP
            elif next_so is None:
                new_so = prev_so + _SORT_GAP
            else:
                new_so = (prev_so + next_so) / 2
            await conn.execute(
                "UPDATE public.bh_list_items SET sort_order = $2 WHERE id = $1", item_id, new_so)
    return True


async def reorder(list_id: int, ordered_ids: list[int], user_id: int = 1) -> bool:
    """Full transactional re-sequence of a list to the given id order (R3.4)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            return False
        async with conn.transaction():
            for idx, item_id in enumerate(ordered_ids, start=1):
                await conn.execute(
                    "UPDATE public.bh_list_items SET sort_order = $3 "
                    "WHERE id = $1 AND list_id = $2", item_id, list_id, idx * _SORT_GAP)
    return True


# ---- List lifecycle (create is above; rename/retype/archive/delete) ---------

async def rename_list(list_id: int, name: str, user_id: int = 1) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            return False
        try:
            await conn.execute(
                "UPDATE public.bh_lists SET name = $2, updated_at = NOW() WHERE id = $1",
                list_id, name.strip())
        except Exception as e:
            if "uq_lists_shared_name" in str(e) or "uq_lists_private_name" in str(e):
                raise ListError(f"A list named '{name.strip()}' already exists.") from e
            raise
    return True


async def set_list_type(list_id: int, list_type_id: int, user_id: int = 1) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            return False
        await conn.execute(
            "UPDATE public.bh_lists SET list_type_id = $2, updated_at = NOW() WHERE id = $1",
            list_id, list_type_id)
    return True


async def set_archived(list_id: int, archived: bool, user_id: int = 1) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            return False
        await conn.execute(
            "UPDATE public.bh_lists SET is_archived = $2, updated_at = NOW() WHERE id = $1",
            list_id, archived)
    return True


async def delete_list(list_id: int, user_id: int = 1) -> bool:
    """Hard-delete a list (cascades items). The router gates this on explicit confirm."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _list_accessible(conn, list_id, user_id):
            return False
        await conn.execute("DELETE FROM public.bh_lists WHERE id = $1", list_id)
    return True


# ---- Helpers ----------------------------------------------------------------

def _parse_quantity(text: str) -> tuple[Optional[str], str]:
    """Try to extract a quantity prefix from an item. Returns (quantity, clean_text)."""
    import re
    # Match patterns like "2 lbs chicken", "1 dozen eggs", "3x paper towels"
    m = re.match(r'^(\d+(?:\.\d+)?\s*(?:lbs?|oz|kg|g|dozen|doz|x|ct|pack|bunch|bag|box|can|jar|bottle)?)\s+(.+)', text, re.IGNORECASE)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return None, text


def _format_list(list_name: str, items: list[dict], show_checked: bool) -> str:
    """Format a list for chat display."""
    if not items:
        return f"📋 **{list_name.title()}** — empty! Add items with: *add X to my {list_name} list*"

    unchecked = [i for i in items if not i["checked"]]
    checked = [i for i in items if i["checked"]]

    lines = [f"## 📋 {list_name.title()}", ""]

    if unchecked:
        for i in unchecked:
            qty = f" ({i['quantity']})" if i.get("quantity") else ""
            lines.append(f"- [ ] {i['text']}{qty}")

    if show_checked and checked:
        lines.append("")
        lines.append("*Checked off:*")
        for i in checked:
            lines.append(f"- [x] ~~{i['text']}~~")

    lines.append("")
    lines.append(f"*{len(unchecked)} item{'s' if len(unchecked) != 1 else ''} remaining*")

    return "\n".join(lines)
