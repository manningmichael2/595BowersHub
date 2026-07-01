"""Per-domain committer functions (R2.3, R2.7 — NFR: no interpolated SQL).

One explicit function per DOMAIN (not a registry — right-sized for ~13 fixed
domains, per the design's tournament decision). All values are bound with `$n`
placeholders; the only interpolated tokens are code-literal table/column
identifiers, quoted via the canonical `_quote_ident`. `_extra_fields` are folded
into the row's `notes` (preserving the n8n `Plan Commit` behavior).

DB committers run inside the caller's transaction (`commit.py`), so a row + its
asset-link are atomic — a link failure rolls the row back too (no orphan asset,
a strict improvement over the non-transactional n8n flow). Non-DB committers
(shopping_list / knowledge_fact / project / other) delegate to existing services
that manage their own connections and content-dedup.
"""

from __future__ import annotations

import decimal
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _qi(name: str) -> str:
    """Canonical identifier quoter (reused from db_browser, lazy-imported to
    avoid pulling the router at module load)."""
    from backend.routers.db_browser import _quote_ident

    return _quote_ident(name)


# ── value coercion (mirror n8n sqlStr/sqlNum: ""/None → NULL) ──────────────

def _text(v: Any) -> Optional[str]:
    if v is None or v == "":
        return None
    return str(v)


def _dec(v: Any) -> Optional[decimal.Decimal]:
    if v is None or v == "":
        return None
    try:
        return decimal.Decimal(str(v))
    except (decimal.InvalidOperation, ValueError):
        return None


def _int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _bool(v: Any) -> Optional[bool]:
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def _slug(s: Optional[str]) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "untitled").lower().strip())
    s = s.strip("-")[:80]
    return s or "untitled"


def _fold_notes(base: Optional[str], extras: Optional[dict]) -> Optional[str]:
    """Append `_extra_fields` under a divider, matching the n8n Plan Commit."""
    lines = [f"{k}: {v}" for k, v in (extras or {}).items()]
    if lines:
        parts = [base, "--- extra fields ---", *lines]
        return "\n".join(p for p in parts if p)
    return base or None


# ── generic parameterized insert + asset link ──────────────────────────────

async def _insert(conn, schema: str, table: str, columns: Dict[str, Any]) -> int:
    cols = list(columns.keys())
    col_sql = ", ".join(_qi(c) for c in cols)
    ph = ", ".join(f"${i + 1}" for i in range(len(cols)))
    sql = f"INSERT INTO {_qi(schema)}.{_qi(table)} ({col_sql}) VALUES ({ph}) RETURNING id"
    return await conn.fetchval(sql, *[columns[c] for c in cols])


async def _link_asset(
    conn, schema: str, link_table: str, fk_col: str, record_id: int,
    asset_id: Optional[str], file_role: Optional[str] = None,
) -> None:
    if not asset_id:
        return
    import uuid

    cols: List[str] = [fk_col, "asset_id", "is_primary"]
    vals: List[Any] = [record_id, uuid.UUID(str(asset_id)), True]
    if file_role is not None:
        cols = [fk_col, "asset_id", "file_role", "is_primary"]
        vals = [record_id, uuid.UUID(str(asset_id)), file_role, True]
    col_sql = ", ".join(_qi(c) for c in cols)
    ph = ", ".join(f"${i + 1}" for i in range(len(cols)))
    await conn.execute(
        f"INSERT INTO {_qi(schema)}.{_qi(link_table)} ({col_sql}) VALUES ({ph})", *vals
    )


def _ok(domain: str, record_id: Any, summary: str) -> dict:
    return {"ok": True, "domain": domain, "record_id": str(record_id), "summary": summary}


def _err(domain: str, message: str) -> dict:
    return {"ok": False, "domain": domain, "error": message}


# ── typed inventory committers ─────────────────────────────────────────────

async def commit_tool(conn, p: dict, asset_id: Optional[str]) -> dict:
    extras = p.get("_extra_fields") or {}
    base = "; ".join([x for x in (p.get("notes"), p.get("location"), p.get("condition")) if x])
    rid = await _insert(conn, "inventory", "tools", {
        "name": _text(p.get("name") or p.get("brand") or "Unnamed Tool"),
        "brand": _text(p.get("brand")),
        "model": _text(p.get("model")),
        "type": _text(p.get("type")),
        "notes": _fold_notes(base, extras),
    })
    await _link_asset(conn, "inventory", "tool_files", "tool_id", rid, asset_id)
    name = " ".join([x for x in (p.get("brand"), p.get("model"), p.get("name")) if x]) or "(unnamed)"
    return _ok("tool", rid, f"Tool: {name}")


async def commit_router_bit(conn, p: dict, asset_id: Optional[str]) -> dict:
    extras = p.get("_extra_fields") or {}
    rid = await _insert(conn, "inventory", "router_bits", {
        "brand": _text(p.get("brand")),
        "profile": _text(p.get("profile") or "Unknown"),
        "shank_size_in": _dec(p.get("shank_size_in")),
        "cutting_diameter_in": _dec(p.get("cutting_diameter_in")),
        "cutting_length_in": _dec(p.get("cutting_length_in")),
        "has_bearing": _bool(p.get("has_bearing")),
        "set_name": _text(p.get("set_name")),
        "notes": _fold_notes(p.get("notes"), extras),
    })
    await _link_asset(conn, "inventory", "router_bit_files", "router_bit_id", rid, asset_id)
    return _ok("router_bit", rid, f"Router bit: {p.get('brand') or ''} {p.get('profile') or ''}".strip())


async def commit_saw_blade(conn, p: dict, asset_id: Optional[str]) -> dict:
    extras = p.get("_extra_fields") or {}
    rid = await _insert(conn, "inventory", "saw_blades", {
        "brand": _text(p.get("brand")),
        "diameter_in": _dec(p.get("diameter_in")),
        "teeth": _int(p.get("teeth")),
        "kerf_in": _dec(p.get("kerf_in")),
        "type": _text(p.get("type")),
        "notes": _fold_notes(p.get("notes"), extras),
    })
    await _link_asset(conn, "inventory", "saw_blade_files", "saw_blade_id", rid, asset_id)
    return _ok("saw_blade", rid, f"Saw blade: {p.get('brand') or '(unnamed)'}")


async def commit_wood(conn, p: dict, asset_id: Optional[str]) -> dict:
    rid = await _insert(conn, "inventory", "wood", {
        "species": _text(p.get("species")),
        "dimensions": _text(p.get("dimensions")),
        "quantity": _dec(p.get("quantity")),
        "unit": _text(p.get("unit")),
        "notes": _text(p.get("notes")),
    })
    await _link_asset(conn, "inventory", "wood_files", "wood_id", rid, asset_id)
    name = " ".join([x for x in (p.get("species"), p.get("dimensions")) if x]) or "(unspecified)"
    return _ok("wood", rid, f"Wood: {name}")


async def commit_album(conn, p: dict, asset_id: Optional[str]) -> dict:
    rid = await _insert(conn, "inventory", "albums", {
        "title": _text(p.get("title") or "(untitled)"),
        "artist": _text(p.get("artist")),
        "label": _text(p.get("label")),
        "catalog_number": _text(p.get("catalog_number")),
        "year": _int(p.get("year")),
        "condition": _text(p.get("condition")),
        "notes": _text(p.get("notes")),
    })
    await _link_asset(conn, "inventory", "album_files", "album_id", rid, asset_id)
    name = " - ".join([x for x in (p.get("artist"), p.get("title")) if x]) or "(untitled)"
    return _ok("album", rid, f"Album: {name}")


async def commit_manual(conn, p: dict, asset_id: Optional[str]) -> dict:
    title = p.get("title")
    if not title:
        title = f"{p['brand']} {p['model']} manual" if (p.get("brand") and p.get("model")) else "Manual"
    rid = await _insert(conn, "inventory", "manuals", {
        "title": _text(title),
        "brand": _text(p.get("brand")),
        "model": _text(p.get("model")),
        "doc_type": _text(p.get("doc_type")),
        "notes": _text(p.get("notes")),
    })
    await _link_asset(conn, "inventory", "manual_files", "manual_id", rid, asset_id)
    return _ok("manual", rid, f"Manual: {title}")


# ── bespoke DB committers ──────────────────────────────────────────────────

async def commit_house_room(conn, p: dict, asset_id: Optional[str]) -> dict:
    """Upsert by name so re-capturing a room doesn't duplicate."""
    rid = await conn.fetchval(
        f"INSERT INTO {_qi('house')}.{_qi('rooms')} (name, floor, notes) VALUES ($1,$2,$3) "
        "ON CONFLICT (name) DO UPDATE SET notes = COALESCE(EXCLUDED.notes, house.rooms.notes) "
        "RETURNING id",
        _text(p.get("name") or "unnamed"), _int(p.get("floor")), _text(p.get("notes")),
    )
    await _link_asset(conn, "house", "room_files", "room_id", rid, asset_id)
    return _ok("house_room", rid, f"Room: {p.get('name') or '(unnamed)'}")


async def commit_recipe(conn, p: dict, asset_id: Optional[str]) -> dict:
    ingredients = p.get("ingredients") if isinstance(p.get("ingredients"), list) else []
    method = p.get("method") if isinstance(p.get("method"), list) else []
    parts: List[str] = []
    if ingredients:
        parts.append("INGREDIENTS:\n- " + "\n- ".join(str(i) for i in ingredients))
    if method:
        parts.append("METHOD:\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(method)))
    if p.get("notes"):
        parts.append("NOTES:\n" + str(p["notes"]))
    title = p.get("title") or "Untitled Recipe"
    rid = await _insert(conn, "cook", "recipes", {
        "title": _text(title),
        "slug": _slug(p.get("title")),
        "source": _text(p.get("source")),
        "servings": _int(p.get("servings")),
        "notes": _text("\n\n".join(parts)),
    })
    await _link_asset(conn, "cook", "recipe_files", "recipe_id", rid, asset_id, file_role="source_page")
    return _ok("recipe", rid, f"Recipe: {title}")


async def commit_cook_log(conn, p: dict, asset_id: Optional[str]) -> dict:
    q = str(p.get("recipe_query") or p.get("recipe_title") or "").strip()
    if not q:
        return _err("cook_log", "cook_log requires recipe_query (the recipe title to look up).")
    recipe_id = await conn.fetchval(
        f"SELECT id FROM {_qi('cook')}.{_qi('recipes')} WHERE LOWER(title) LIKE LOWER($1) "
        "ORDER BY updated_at DESC LIMIT 1",
        f"%{q}%",
    )
    if recipe_id is None:
        return _err("cook_log", f"No recipe matched '{q}'. Capture the recipe first, then log this cook.")
    cooked_at = _text(p.get("cooked_at"))
    rid = await conn.fetchval(
        f"INSERT INTO {_qi('cook')}.{_qi('cook_log')} "
        "(recipe_id, cooked_at, servings_made, adjustments, rating, notes) "
        "VALUES ($1, COALESCE($2::date, CURRENT_DATE), $3, $4, $5, $6) RETURNING id",
        recipe_id, cooked_at, _int(p.get("servings_made")), _text(p.get("adjustments")),
        _int(p.get("rating")), _text(p.get("notes")),
    )
    return _ok("cook_log", rid, f"Cook log entry for: {q}")


# ── non-DB committers (delegate to existing services) ──────────────────────

async def commit_shopping_list(p: dict, user_id: int) -> dict:
    items = [i for i in (p.get("items") or []) if str(i).strip()]
    if not items:
        return _err("shopping_list", "shopping_list requires a non-empty items array.")
    from backend.services import list_router

    res = await list_router.route_and_add(items, user_id)
    return {"ok": True, "domain": "shopping_list", "added": res.get("added"),
            "needs_disambiguation": res.get("needs_disambiguation"),
            "summary": f"Shopping list: added {len(items)} item(s)"}


async def commit_knowledge_fact(p: dict, user_id: int) -> dict:
    fact = str(p.get("fact") or "").strip()
    if not fact:
        return _err("knowledge_fact", "knowledge_fact requires a fact.")
    topic = str(p.get("topic") or "general").strip()
    from backend.services import knowledge, knowledge_graph

    res = await knowledge.remember(topic, fact)
    if isinstance(res, dict) and res.get("error"):
        return _err("knowledge_fact", res["error"])
    # Mirror the graph as well (best-effort — the fact is already durably saved).
    try:
        await knowledge_graph.remember_entity(
            name=topic, entity_type="topic", summary=fact,
            source="smart-capture", user_id=user_id,
        )
    except Exception as e:  # non-fatal
        logger.warning("knowledge_fact graph mirror failed (fact saved): %s", e)
    return {"ok": True, "domain": "knowledge_fact", "topic": topic,
            "summary": f"Knowledge fact ({topic}): {fact[:80]}"}


async def commit_project(p: dict, user_id: int) -> dict:
    title = str(p.get("title") or "Untitled Project").strip()
    bits = [title]
    for label in ("type", "budget", "goals", "notes"):
        if p.get(label):
            bits.append(f"{label}: {p[label]}")
    from backend.services import knowledge

    res = await knowledge.remember(f"projects/{_slug(title)}", " — ".join(bits))
    if isinstance(res, dict) and res.get("error"):
        return _err("project", res["error"])
    return {"ok": True, "domain": "project", "summary": f"Project: {title}"}


async def commit_other(p: dict, user_id: int) -> dict:
    title = str(p.get("suggested_title") or "capture").strip()
    content = str(p.get("content") or title).strip()
    from backend.services import knowledge

    res = await knowledge.remember(f"captures/{_slug(title)}", content)
    if isinstance(res, dict) and res.get("error"):
        return _err("other", res["error"])
    return {"ok": True, "domain": "other", "summary": f"Capture: {title}"}


# Domains whose committer takes (conn, payload, asset_id) and runs in the caller's
# transaction; the rest take (payload, user_id) and manage their own connection.
DB_DOMAINS = frozenset(
    {"tool", "router_bit", "saw_blade", "wood", "album", "manual", "house_room", "recipe", "cook_log"}
)

DB_COMMITTERS = {
    "tool": commit_tool,
    "router_bit": commit_router_bit,
    "saw_blade": commit_saw_blade,
    "wood": commit_wood,
    "album": commit_album,
    "manual": commit_manual,
    "house_room": commit_house_room,
    "recipe": commit_recipe,
    "cook_log": commit_cook_log,
}

SERVICE_COMMITTERS = {
    "shopping_list": commit_shopping_list,
    "knowledge_fact": commit_knowledge_fact,
    "project": commit_project,
    "other": commit_other,
}
