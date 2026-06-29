"""
Lists Service — shopping lists, to-do lists, packing lists, etc.

Items can be added, checked off, unchecked, and removed via chat or DB Admin.
Lists are household-shared by default (is_shared) — both members add to and check
off one list — while a list can still be private to its creator (is_shared=false).
Resolution prefers the shared list of a given name (see `_resolve_list_id`).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)


async def _resolve_list_id(conn, list_name: str, user_id: int, create: bool = False) -> Optional[int]:
    """Resolve a list the user may access — a shared list of that name (any
    member), or the user's own private list — preferring shared. Optionally
    create it (shared by default) if absent."""
    row = await conn.fetchrow(
        "SELECT id FROM public.bh_lists "
        "WHERE LOWER(name) = LOWER($1) AND (is_shared OR user_id = $2) "
        "ORDER BY is_shared DESC, id LIMIT 1",
        list_name.strip(), user_id,
    )
    if row:
        return row["id"]
    if create:
        row = await conn.fetchrow(
            "INSERT INTO public.bh_lists (name, user_id) VALUES ($1, $2) RETURNING id",
            list_name.strip(), user_id,  # is_shared defaults true
        )
        return row["id"]
    return None


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


async def get_all_lists(user_id: int = 1) -> dict:
    """Get all lists the user can see (household-shared + their own private) with
    item counts."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT l.name, l.description,
                   COUNT(i.id) FILTER (WHERE i.checked = false) as pending,
                   COUNT(i.id) FILTER (WHERE i.checked = true) as done
            FROM public.bh_lists l
            LEFT JOIN public.bh_list_items i ON i.list_id = l.id
            WHERE (l.is_shared OR l.user_id = $1) AND l.is_archived = false
            GROUP BY l.id, l.name, l.description
            ORDER BY l.updated_at DESC
        """, user_id)

    if not rows:
        return {"_display": "You don't have any lists yet. Try: *add milk to my shopping list*"}

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


async def delete_item(item_id: int, user_id: int = 1) -> bool:
    """Delete a single item by id. Returns False if not accessible."""
    pool = get_pool()
    async with pool.acquire() as conn:
        if not await _item_accessible(conn, item_id, user_id):
            return False
        await conn.execute("DELETE FROM public.bh_list_items WHERE id = $1", item_id)
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
