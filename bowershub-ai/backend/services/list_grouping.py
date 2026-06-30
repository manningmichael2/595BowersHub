"""
List grouping / sorting / filtering + grocery auto-categorize.

One parameterized mechanism renders every list type: group by the type's declared
``group_by`` field, order groups by an active store's aisle layout (else the
type's category_set), sort via a fixed validated whitelist, and filter by the
type's fields. Sort identifiers are whitelisted or schema-validated (never
interpolated from user input); filter values are always bound params. See
``.kiro/specs/lists-v2/design.md`` (R5.1–R5.6).
"""
from __future__ import annotations

import re
from typing import Optional

from backend.services import list_config, list_schema

# Fixed sort whitelist — algorithms are code (security), the per-type DEFAULT is data.
_SORTS = {
    "manual": "sort_order",
    "name": "LOWER(text)",
    "due": "due_date",
    "recent": "created_at",
    "checked": "checked",
}


def _sort_expr(sort_key: str, schema: list_schema.EffectiveSchema) -> str:
    """Resolve a sort key to a SQL expression. Built-ins come from the whitelist;
    a custom sortable attribute field is validated against the schema + a strict
    identifier pattern, then cast by col_type. Anything else → manual order."""
    if sort_key in _SORTS:
        return _SORTS[sort_key]
    f = schema.field(sort_key)
    if f and f.storage == "attribute" and f.sortable and re.match(r"^[a-z0-9_]+$", sort_key):
        if f.col_type == "number":
            return f"(attributes->>'{sort_key}')::numeric"
        if f.col_type == "date":
            return f"(attributes->>'{sort_key}')::timestamptz"
        return f"attributes->>'{sort_key}'"
    return "sort_order"


async def categorize(conn, list_type_id: Optional[int], text: str) -> Optional[str]:
    """Cheap department lookup for an item (R5.5): exact alias match, then the
    longest contained alias. Returns None if nothing matches (an Ollama fallback
    can be layered later; on any failure the item is simply left uncategorized)."""
    t = text.strip().lower()
    if not t:
        return None
    exact = await conn.fetchval(
        "SELECT department FROM public.bh_item_category_aliases "
        "WHERE (list_type_id = $1 OR list_type_id IS NULL) AND LOWER(alias) = $2 "
        "ORDER BY (list_type_id IS NOT NULL) DESC LIMIT 1",
        list_type_id, t)
    if exact:
        return exact
    return await conn.fetchval(
        "SELECT department FROM public.bh_item_category_aliases "
        "WHERE (list_type_id = $1 OR list_type_id IS NULL) AND $2 LIKE '%' || LOWER(alias) || '%' "
        "ORDER BY length(alias) DESC LIMIT 1",
        list_type_id, t)


async def grouped_view(conn, list_id: int, *, store: Optional[str] = None,
                       sort: Optional[str] = None, group: bool = True,
                       filters: Optional[dict] = None) -> dict:
    """Return a list's items grouped + sorted + filtered. ``filters`` may carry
    category / assignee_user_id / checked. ``store`` activates store filtering +
    aisle ordering."""
    ltype = await conn.fetchrow(
        "SELECT t.id, t.group_by, t.default_sort, t.category_set "
        "FROM public.bh_lists l JOIN public.bh_list_types t ON t.id = l.list_type_id "
        "WHERE l.id = $1", list_id)
    schema = await list_schema.resolve_schema(conn, list_id)
    sort_key = sort or (ltype["default_sort"] if ltype else "recent")
    sort_sql = _sort_expr(sort_key, schema)

    where = ["list_id = $1"]
    args: list = [list_id]
    filters = filters or {}
    if "checked" in filters and filters["checked"] is not None:
        args.append(filters["checked"]); where.append(f"checked = ${len(args)}")
    if filters.get("category"):
        args.append(filters["category"]); where.append(f"category = ${len(args)}")
    if filters.get("assignee_user_id"):
        args.append(filters["assignee_user_id"]); where.append(f"assignee_user_id = ${len(args)}")
    if store:
        # Items tagged with this store, plus untagged items (they apply everywhere).
        # The store field is a multi_select keyed 'store' → a JSONB array of names.
        args.append(store)
        where.append(
            f"(NOT (attributes ? 'store') OR attributes->'store' ? ${len(args)})")

    rows = await conn.fetch(
        f"SELECT id, text, quantity, checked, added_by, category, due_date, "
        f"       assignee_user_id, sort_order, attributes "
        f"FROM public.bh_list_items WHERE {' AND '.join(where)} "
        f"ORDER BY checked, {sort_sql} NULLS LAST, id",
        *args)
    items = [dict(r) for r in rows]

    group_by = ltype["group_by"] if ltype else None
    if not group or not group_by:
        return {"group_by": None, "sort": sort_key, "groups": [{"key": None, "label": None, "items": items}]}

    # Bucket items by the group_by field value (preserving sort order within).
    buckets: dict = {}
    for it in items:
        key = it.get(group_by) if group_by in it else (it.get("attributes") or {}).get(group_by)
        buckets.setdefault(key, []).append(it)

    order = await _group_order(conn, group_by, ltype, store, list(buckets.keys()))
    labels = await _group_labels(conn, group_by, order)
    groups = [{"key": k, "label": labels.get(k, k if k is not None else "Uncategorized"),
               "items": buckets[k]} for k in order if k in buckets]
    return {"group_by": group_by, "sort": sort_key, "groups": groups}


async def _group_order(conn, group_by: str, ltype, store: Optional[str], keys: list) -> list:
    """Order the group keys: store aisle order (if active) else the type's
    category_set order else alphabetical; unknown/None bucket last."""
    ordered: list = []
    if group_by == "category":
        seq = None
        if store:
            seq = await list_config.store_aisle_order(conn, store)
        if not seq and ltype and ltype["category_set"]:
            seq = [c["key"] for c in ltype["category_set"]]
        if seq:
            ordered = [k for k in seq if k in keys]
    remaining = [k for k in keys if k not in ordered and k is not None]
    remaining.sort(key=lambda x: str(x).lower())
    tail = [k for k in keys if k is None]
    return ordered + remaining + tail


async def _group_labels(conn, group_by: str, keys: list) -> dict:
    if group_by == "assignee_user_id":
        ids = [k for k in keys if k is not None]
        if ids:
            rows = await conn.fetch(
                "SELECT id, display_name FROM public.bh_users WHERE id = ANY($1)", ids)
            return {r["id"]: r["display_name"] for r in rows}
    return {}
