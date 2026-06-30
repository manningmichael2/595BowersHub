"""
List Router — decide which list a free-text item belongs to.

Specialises the existing tiered router instead of forking it: a deterministic
name/embedding pass resolves the obvious majority; the expensive model is only
needed for genuine ambiguity. Key guarantees (R4.3/R4.5):
  • never auto-creates a list from a misheard name — unmatched items go to the
    elected default list (lazily created once if none exists);
  • degrades gracefully — if embeddings/Ollama are unavailable the add still
    succeeds via the default/explicit list; routing never blocks or drops an item.

The cosine scoring uses list embeddings written to kb_chunks by the embedding
worker (source_type='list'); thresholds live in bh_platform_settings and are
DB-tunable. The threshold DECISION is a pure function (_decide) so it is fully
testable without a model.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from backend.services import list_config
from backend.services import lists as svc

logger = logging.getLogger(__name__)

DEFAULT_LIST_NAME = "Shopping"


def _decide(scored: list[dict], cfg: dict, has_create_verb: bool = False) -> dict:
    """Pure threshold decision over [{id,name,sim}] sorted desc by sim.
    Returns {action: match|disambiguate|fallback, ...}."""
    match = cfg.get("match_threshold", 0.55)
    margin = cfg.get("ambiguity_margin", 0.07)
    if not scored:
        return {"action": "fallback"}
    best = scored[0]
    second = scored[1] if len(scored) > 1 else None
    if best["sim"] >= match:
        if second and (best["sim"] - second["sim"]) < margin:
            return {"action": "disambiguate", "candidates": [best, second]}
        return {"action": "match", "list": best}
    return {"action": "fallback"}


def _vec_literal(vec: list[float]) -> str:
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


async def _score_lists(conn, vec: list[float], user_id: int) -> list[dict]:
    """Cosine sim of an item vector vs accessible, non-archived list embeddings."""
    rows = await conn.fetch(
        "SELECT l.id, l.name, 1 - (c.embedding <=> $1::halfvec) AS sim "
        "FROM public.kb_chunks c JOIN public.bh_lists l ON l.id = c.source_id "
        "WHERE c.source_type = 'list' AND c.embedding IS NOT NULL "
        "  AND (l.is_shared OR l.user_id = $2) AND l.is_archived = false "
        "ORDER BY sim DESC",
        _vec_literal(vec), user_id)
    return [{"id": r["id"], "name": r["name"], "sim": float(r["sim"])} for r in rows]


async def ensure_default_list(conn, user_id: int) -> int:
    """Return the elected default list id, lazily creating a shared 'Shopping'
    list once if none is set (or the set one was archived/deleted). This is the
    ONE sanctioned system auto-create — it keeps the no-drop guarantee on a fresh
    install without ever spawning junk from a misheard name (R4.3/R4.5)."""
    default_id = await list_config.get_default_list_id(conn)
    if default_id is not None:
        live = await conn.fetchval(
            "SELECT 1 FROM public.bh_lists WHERE id = $1 AND is_archived = false", default_id)
        if live:
            return default_id
    existing = await svc.resolve_only(conn, DEFAULT_LIST_NAME, user_id)
    list_id = existing if existing is not None else await svc.create_list(
        conn, DEFAULT_LIST_NAME, user_id)
    await list_config.set_default_list_id(conn, list_id)
    return list_id


async def route_item(conn, text: str, user_id: int,
                     embedder: Optional[Callable] = None) -> dict:
    """Resolve one free-text item to a target list. Returns
    {list_id, list_name?, fallback|matched|needs_disambiguation, candidates?}."""
    if embedder is not None:
        try:
            cfg = await list_config.routing_config(conn)
            vec = await embedder(text)
            scored = await _score_lists(conn, vec, user_id)
            decision = _decide(scored, cfg)
            if decision["action"] == "match":
                return {"list_id": decision["list"]["id"],
                        "list_name": decision["list"]["name"], "matched": True}
            if decision["action"] == "disambiguate":
                return {"needs_disambiguation": True, "candidates": decision["candidates"]}
        except Exception:  # EmbeddingError / Ollama down / pgvector issue → degrade
            logger.debug("embedding route failed for %r; falling back", text, exc_info=True)
    list_id = await ensure_default_list(conn, user_id)
    return {"list_id": list_id, "fallback": True}


async def route_and_add(items, user_id: int, explicit_list: Optional[str] = None,
                        embedder: Optional[Callable] = None) -> dict:
    """Skill entry point: route each item to a list and add it. With an explicit,
    resolvable list name everything goes there; otherwise each item is routed.
    Never creates a list from an unresolved explicit name (avoids junk)."""
    pool = svc.get_pool()
    added_by_list: dict[int, list] = {}
    questions: list[dict] = []
    async with pool.acquire() as conn:
        forced_id = None
        if explicit_list:
            forced_id = await svc.resolve_only(conn, explicit_list, user_id)
        for raw in items:
            text = raw if isinstance(raw, str) else raw.get("text", "")
            if not str(text).strip():
                continue
            if forced_id is not None:
                target = forced_id
            else:
                routed = await route_item(conn, text, user_id, embedder=embedder)
                if routed.get("needs_disambiguation"):
                    questions.append({"text": text,
                                      "candidates": [c["name"] for c in routed["candidates"]]})
                    continue
                target = routed["list_id"]
            added_by_list.setdefault(target, []).append(raw)
    # Add per target list (add_items_by_id manages its own connection + validation).
    summary = []
    for list_id, list_items in added_by_list.items():
        out = await svc.add_items_by_id(list_id, list_items, user_id=user_id)
        summary.append({"list_id": list_id, "added": out["added"]})
    return {"added": summary, "needs_disambiguation": questions}
