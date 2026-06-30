"""
List Schema Engine — the single source of truth for a list's fields.

Every field a list can hold is a row in ``bh_list_field_defs`` across three
scopes that merge by ``key`` with precedence **list > type > core** into one
*effective schema*. That merged schema drives the React renderer, server-side
value validation, AND the AI's understanding of each list — one contract.

A field's ``storage`` says where its value physically lives: ``column`` →  a real
typed column on ``bh_list_items`` (fast/indexed, the built-in cross-cutting
fields); ``attribute`` → the JSONB ``attributes`` tail (the user-extensible,
per-type/per-list fields). Callers validate + partition item values through here
so core columns and the JSONB tail are handled uniformly. See
``.kiro/specs/lists-v2/design.md`` (Schema layer / R1.4 / R1.5).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime
from typing import Any, Optional

# Column-storage fields the writer is allowed to target (defence-in-depth: a
# stray storage='column' field-def can never write to an arbitrary column).
WRITABLE_COLUMNS = {
    "text", "checked", "quantity", "notes",
    "category", "due_date", "assignee_user_id", "sort_order",
}

COL_TYPES = {"text", "number", "date", "checkbox", "single_select", "multi_select", "url"}


class ListSchemaError(ValueError):
    """A value failed validation against its field definition (maps to HTTP 422)."""


@dataclass
class FieldDef:
    key: str
    label: str
    col_type: str
    storage: str                       # 'column' | 'attribute'
    scope: str                         # 'core' | 'type' | 'list'
    required: bool = False
    is_active: bool = True
    groupable: bool = False
    sortable: bool = False
    filterable: bool = False
    options: Optional[list[dict]] = None       # resolved [{value,label,...}]
    options_source: Optional[str] = None       # 'stores' | 'users' | None
    validation: Optional[dict] = None          # {min,max,regex}
    sort_order: int = 0

    @property
    def option_values(self) -> set:
        return {o["value"] for o in (self.options or [])}


@dataclass
class EffectiveSchema:
    fields: list[FieldDef] = dc_field(default_factory=list)   # active, ordered

    def by_key(self) -> dict[str, FieldDef]:
        return {f.key: f for f in self.fields}

    def field(self, key: str) -> Optional[FieldDef]:
        return self.by_key().get(key)


def _row_to_field(row) -> FieldDef:
    return FieldDef(
        key=row["key"], label=row["label"], col_type=row["col_type"],
        storage=row["storage"], scope=row["scope"], required=row["required"],
        is_active=row["is_active"], groupable=row["groupable"],
        sortable=row["sortable"], filterable=row["filterable"],
        options=row["options"], options_source=row["options_source"],
        validation=row["validation"], sort_order=row["sort_order"],
    )


async def _resolve_options(conn, fields: list[FieldDef]) -> None:
    """Concretise options for select fields whose options come from a table, so
    validation and the renderer share one source. Mutates fields in place."""
    needs_stores = any(f.options_source == "stores" for f in fields)
    needs_users = any(f.options_source == "users" for f in fields)
    stores = users = None
    if needs_stores:
        rows = await conn.fetch(
            "SELECT name FROM public.bh_stores WHERE is_active ORDER BY sort_order, LOWER(name)")
        stores = [{"value": r["name"], "label": r["name"]} for r in rows]
    if needs_users:
        rows = await conn.fetch(
            "SELECT id, display_name FROM public.bh_users ORDER BY display_name")
        users = [{"value": r["id"], "label": r["display_name"]} for r in rows]
    for f in fields:
        if f.options_source == "stores":
            f.options = stores
        elif f.options_source == "users":
            f.options = users


async def resolve_schema(conn, list_id: int) -> EffectiveSchema:
    """Merge core → type → list field defs for ``list_id`` into the effective
    schema (precedence list > type > core; inactive fields dropped; ordered)."""
    type_id = await conn.fetchval(
        "SELECT list_type_id FROM public.bh_lists WHERE id = $1", list_id)
    rows = await conn.fetch(
        "SELECT * FROM public.bh_list_field_defs "
        "WHERE scope = 'core' "
        "   OR (scope = 'type' AND list_type_id = $1) "
        "   OR (scope = 'list' AND list_id = $2)",
        type_id, list_id,
    )
    # Merge by key with scope precedence; a higher scope fully replaces the field.
    rank = {"core": 0, "type": 1, "list": 2}
    merged: dict[str, FieldDef] = {}
    for row in rows:
        f = _row_to_field(row)
        cur = merged.get(f.key)
        if cur is None or rank[f.scope] >= rank[cur.scope]:
            merged[f.key] = f
    active = [f for f in merged.values() if f.is_active]
    await _resolve_options(conn, active)
    active.sort(key=lambda f: (f.sort_order, f.key))
    return EffectiveSchema(fields=active)


# ── Validation ───────────────────────────────────────────────────────────────

def _as_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ListSchemaError("expected a number, got a boolean")
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            pass
    raise ListSchemaError(f"expected a number, got {value!r}")


def validate_value(field: FieldDef, value: Any) -> None:
    """Raise ListSchemaError if ``value`` doesn't fit ``field``'s col_type/rules.
    ``None`` is allowed unless the field is required."""
    if value is None:
        if field.required:
            raise ListSchemaError(f"'{field.label}' is required")
        return

    ct = field.col_type
    if ct == "text":
        if not isinstance(value, str):
            raise ListSchemaError(f"'{field.label}' must be text")
    elif ct == "number":
        n = _as_number(value)
        v = field.validation or {}
        if "min" in v and n < v["min"]:
            raise ListSchemaError(f"'{field.label}' must be ≥ {v['min']}")
        if "max" in v and n > v["max"]:
            raise ListSchemaError(f"'{field.label}' must be ≤ {v['max']}")
    elif ct == "checkbox":
        if not isinstance(value, bool):
            raise ListSchemaError(f"'{field.label}' must be true/false")
    elif ct == "date":
        if isinstance(value, (date, datetime)):
            return
        if not isinstance(value, str):
            raise ListSchemaError(f"'{field.label}' must be a date")
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ListSchemaError(f"'{field.label}' must be an ISO date")
    elif ct == "url":
        if not isinstance(value, str) or not re.match(r"^https?://", value.strip(), re.I):
            raise ListSchemaError(f"'{field.label}' must be an http(s) URL")
    elif ct == "single_select":
        if value not in field.option_values:
            raise ListSchemaError(f"'{value}' is not a valid option for '{field.label}'")
    elif ct == "multi_select":
        if not isinstance(value, list):
            raise ListSchemaError(f"'{field.label}' must be a list of options")
        bad = [v for v in value if v not in field.option_values]
        if bad:
            raise ListSchemaError(f"invalid option(s) for '{field.label}': {bad}")
    else:  # pragma: no cover - CHECK constraint prevents this
        raise ListSchemaError(f"unknown field type {ct!r}")

    # Optional regex on text-like fields.
    if ct in ("text", "url") and field.validation and field.validation.get("regex"):
        if not re.search(field.validation["regex"], str(value)):
            raise ListSchemaError(f"'{field.label}' has an invalid format")


def field_to_dict(f: FieldDef) -> dict:
    """Serialise a field def for the API (renderer reads this)."""
    return {
        "key": f.key, "label": f.label, "col_type": f.col_type, "storage": f.storage,
        "scope": f.scope, "required": f.required, "groupable": f.groupable,
        "sortable": f.sortable, "filterable": f.filterable, "options": f.options,
        "options_source": f.options_source, "sort_order": f.sort_order,
    }


# ── Field-definition mutation (per-list overrides; integrity-guarded, R6.5) ───

async def create_list_field(conn, list_id: int, key: str, label: str, col_type: str,
                            options: Optional[list] = None, required: bool = False) -> None:
    """Add a user-defined custom column to a single list (scope='list')."""
    if col_type not in COL_TYPES:
        raise ListSchemaError(f"unknown column type {col_type!r}")
    if not re.match(r"^[a-z0-9_]+$", key or ""):
        raise ListSchemaError("field key must be lowercase letters, numbers, underscores")
    exists = await conn.fetchval(
        "SELECT 1 FROM public.bh_list_field_defs WHERE scope='list' AND list_id=$1 AND key=$2",
        list_id, key)
    if exists:
        raise ListSchemaError(f"this list already has a field '{key}'")
    await conn.execute(
        "INSERT INTO public.bh_list_field_defs "
        "(scope, list_id, key, label, col_type, storage, options, required, "
        " groupable, sortable, filterable) "
        "VALUES ('list',$1,$2,$3,$4,'attribute',$5::jsonb,$6,$7,$7,$7)",
        list_id, key, label, col_type,
        json.dumps(options) if options is not None else None,
        required, col_type in ("single_select", "multi_select", "text", "date", "number"),
    )


async def _ensure_list_override(conn, list_id: int, key: str):
    """Return the scope='list' override row for (list_id,key), creating it from the
    underlying core/type def if absent. Core/type rows themselves are NEVER mutated
    — this is the integrity boundary that stops a per-list edit changing a field for
    every list, and (since it's keyed by list_id) stops cross-list mutation."""
    row = await conn.fetchrow(
        "SELECT * FROM public.bh_list_field_defs WHERE scope='list' AND list_id=$1 AND key=$2",
        list_id, key)
    if row:
        return row
    # Find the underlying core/type def this list resolves for that key.
    type_id = await conn.fetchval("SELECT list_type_id FROM public.bh_lists WHERE id=$1", list_id)
    base = await conn.fetchrow(
        "SELECT * FROM public.bh_list_field_defs "
        "WHERE (scope='type' AND list_type_id=$1 AND key=$2) OR (scope='core' AND key=$2) "
        "ORDER BY (scope='type') DESC LIMIT 1", type_id, key)
    if base is None:
        raise ListSchemaError(f"no field '{key}' on this list")
    new_id = await conn.fetchval(
        "INSERT INTO public.bh_list_field_defs "
        "(scope, list_id, key, label, col_type, storage, options, options_source, "
        " required, groupable, sortable, filterable, sort_order) "
        "VALUES ('list',$1,$2,$3,$4,$5,$6::jsonb,$7,$8,$9,$10,$11,$12) RETURNING id",
        list_id, key, base["label"], base["col_type"], base["storage"],
        json.dumps(base["options"]) if base["options"] is not None else None,
        base["options_source"], base["required"], base["groupable"],
        base["sortable"], base["filterable"], base["sort_order"])
    return await conn.fetchrow("SELECT * FROM public.bh_list_field_defs WHERE id=$1", new_id)


async def update_list_field(conn, list_id: int, key: str, *, label: Optional[str] = None,
                            sort_order: Optional[int] = None, is_active: Optional[bool] = None,
                            options: Optional[list] = None) -> None:
    """Rename / reorder / soft-remove / re-option a field FOR THIS LIST ONLY, by
    writing a scope='list' override (R6.5). A core field can be hidden for one list
    (is_active=false) without affecting any other list or the core definition."""
    await _ensure_list_override(conn, list_id, key)
    sets, args = [], []
    if label is not None:
        args.append(label); sets.append(f"label=${len(args)}")
    if sort_order is not None:
        args.append(sort_order); sets.append(f"sort_order=${len(args)}")
    if is_active is not None:
        args.append(is_active); sets.append(f"is_active=${len(args)}")
    if options is not None:
            args.append(json.dumps(options)); sets.append(f"options=${len(args)}::jsonb")
    if not sets:
        return
    args.extend([list_id, key])
    await conn.execute(
        f"UPDATE public.bh_list_field_defs SET {', '.join(sets)}, updated_at=now() "
        f"WHERE scope='list' AND list_id=${len(args)-1} AND key=${len(args)}", *args)


def partition_item_values(
    schema: EffectiveSchema, values: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate each submitted ``{key: value}`` against the effective schema and
    split it by storage into (column_values, attribute_values). Unknown keys and
    non-writable column targets raise ListSchemaError — nothing is silently
    dropped or written to an unexpected column."""
    columns: dict[str, Any] = {}
    attributes: dict[str, Any] = {}
    for key, value in values.items():
        f = schema.field(key)
        if f is None:
            raise ListSchemaError(f"unknown field '{key}' for this list")
        validate_value(f, value)
        if f.storage == "column":
            if f.key not in WRITABLE_COLUMNS:
                raise ListSchemaError(f"field '{key}' is not a writable column")
            columns[f.key] = value
        else:
            attributes[f.key] = value
    return columns, attributes
