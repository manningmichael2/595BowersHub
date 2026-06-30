"""
Knowledge Graph Service — structured memory for the AI.

Replaces grep-based markdown recall with a queryable entity-relationship graph.
The old markdown /knowledge/ directory is preserved as an archive and still
searchable via the legacy recall path — this is additive, not destructive.

Key operations:
  - remember_entity(): Create or update an entity
  - remember_relationship(): Connect two entities
  - recall_entities(): Search entities by name, type, or attributes
  - recall_related(): Find everything connected to an entity
  - recall_graph(): Full-text search across the entire knowledge graph
"""
import json
import logging
from typing import Any, Dict, List, Optional

from backend.database import get_pool
from backend.config import load_config
from backend.services.embeddings import EmbeddingsClient
from backend.services.hybrid_retrieval import HybridRetriever

logger = logging.getLogger(__name__)

# Cached hybrid retriever for knowledge graph search (R3.3)
_hybrid_retriever: Optional[HybridRetriever] = None


def _get_hybrid_retriever():
    global _hybrid_retriever
    if _hybrid_retriever is None:
        try:
            config = load_config()
            pool = get_pool()
            client = EmbeddingsClient(config.OLLAMA_URL, pool)
            _hybrid_retriever = HybridRetriever(client, pool)
        except Exception as e:
            logger.warning(f"Failed to initialize hybrid retriever: {e}")
    return _hybrid_retriever


# ---- Write Operations --------------------------------------------------------

async def remember_entity(
    name: str,
    entity_type: str,
    summary: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
    source: str = "chat",
    user_id: Optional[int] = None,
    visibility: str = "shared",
) -> dict:
    """
    Create or update an entity in the knowledge graph.
    If an entity with the same name and type exists, updates it (merge attributes).

    `visibility` ('shared'|'private') is applied only on INSERT. Manual /remember
    leaves it 'shared'; the Context Harvester passes 'private' so auto-captured
    facts are scoped to their author on the recall path (see hybrid_retrieval).
    On UPDATE the existing visibility is preserved — a re-capture must never flip
    a fact a user already shared (or kept private) to the other state.

    Returns the entity dict.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Check for existing entity (case-insensitive name + same type)
        existing = await conn.fetchrow("""
            SELECT id, attributes FROM public.bh_entities
            WHERE LOWER(name) = LOWER($1) AND entity_type = $2 AND is_active = true
        """, name.strip(), entity_type.strip())

        if existing:
            # Merge attributes
            merged_attrs = dict(existing["attributes"] or {})
            if attributes:
                merged_attrs.update(attributes)

            row = await conn.fetchrow("""
                UPDATE public.bh_entities
                SET summary = COALESCE($2, summary),
                    attributes = $3::jsonb,
                    updated_at = NOW(),
                    source = $4
                WHERE id = $1
                RETURNING *
            """, existing["id"], summary, json.dumps(merged_attrs), source)
        else:
            row = await conn.fetchrow("""
                INSERT INTO public.bh_entities (name, entity_type, summary, attributes, source, created_by, visibility)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                RETURNING *
            """, name.strip(), entity_type.strip(), summary,
                json.dumps(attributes or {}), source, user_id, visibility)

    logger.info(f"Knowledge graph: {'updated' if existing else 'created'} entity '{name}' ({entity_type})")
    return dict(row)


async def remember_relationship(
    from_name: str,
    to_name: str,
    relationship: str,
    from_type: Optional[str] = None,
    to_type: Optional[str] = None,
    attributes: Optional[Dict[str, Any]] = None,
    source: str = "chat",
) -> dict:
    """
    Create a relationship between two entities.
    Creates the entities if they don't exist (with inferred types).
    
    Returns the relationship dict.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Find or create "from" entity
        from_entity = await conn.fetchrow("""
            SELECT id FROM public.bh_entities
            WHERE LOWER(name) = LOWER($1) AND is_active = true
            ORDER BY CASE WHEN entity_type = $2 THEN 0 ELSE 1 END
            LIMIT 1
        """, from_name.strip(), from_type or "thing")

        if not from_entity:
            from_entity = await conn.fetchrow("""
                INSERT INTO public.bh_entities (name, entity_type, source)
                VALUES ($1, $2, $3) RETURNING id
            """, from_name.strip(), from_type or "thing", source)

        # Find or create "to" entity
        to_entity = await conn.fetchrow("""
            SELECT id FROM public.bh_entities
            WHERE LOWER(name) = LOWER($1) AND is_active = true
            ORDER BY CASE WHEN entity_type = $2 THEN 0 ELSE 1 END
            LIMIT 1
        """, to_name.strip(), to_type or "thing")

        if not to_entity:
            to_entity = await conn.fetchrow("""
                INSERT INTO public.bh_entities (name, entity_type, source)
                VALUES ($1, $2, $3) RETURNING id
            """, to_name.strip(), to_type or "thing", source)

        # Create relationship (upsert)
        row = await conn.fetchrow("""
            INSERT INTO public.bh_relationships (from_entity_id, to_entity_id, relationship, attributes, source)
            VALUES ($1, $2, $3, $4::jsonb, $5)
            ON CONFLICT (from_entity_id, to_entity_id, relationship) DO UPDATE
                SET attributes = EXCLUDED.attributes, is_active = true
            RETURNING *
        """, from_entity["id"], to_entity["id"], relationship.strip(),
            json.dumps(attributes or {}), source)

    logger.info(f"Knowledge graph: relationship '{from_name}' --[{relationship}]--> '{to_name}'")
    return dict(row)


# ---- Read Operations ---------------------------------------------------------

async def recall_entities(
    query: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 20,
    user_id: Optional[int] = None,
) -> List[dict]:
    """
    Search entities by name (full-text), type, or both.
    Returns a list of entity dicts with their relationship counts.

    `user_id` is the viewer: results are scoped to shared facts plus the viewer's
    own private facts (privacy boundary, migration 0057). None = shared only.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        conditions = ["e.is_active = true"]
        params = []
        idx = 1

        # Privacy scope: shared, or the viewer's own private facts.
        conditions.append(
            f"(e.visibility = 'shared' "
            f"OR (${idx}::int IS NOT NULL AND e.created_by = ${idx}::int))"
        )
        params.append(user_id)
        idx += 1

        if query:
            conditions.append(f"to_tsvector('english', e.name || ' ' || COALESCE(e.summary, '')) @@ plainto_tsquery('english', ${idx})")
            params.append(query)
            idx += 1

        if entity_type:
            conditions.append(f"e.entity_type = ${idx}")
            params.append(entity_type)
            idx += 1

        params.append(limit)
        where = " AND ".join(conditions)

        rows = await conn.fetch(f"""
            SELECT e.*,
                   (SELECT COUNT(*) FROM public.bh_relationships r 
                    WHERE (r.from_entity_id = e.id OR r.to_entity_id = e.id) AND r.is_active = true) as connection_count
            FROM public.bh_entities e
            WHERE {where}
            ORDER BY e.updated_at DESC
            LIMIT ${idx}
        """, *params)

    return [dict(r) for r in rows]


async def recall_related(entity_name: str, depth: int = 1) -> dict:
    """
    Find everything related to an entity (1 or 2 hops).
    Returns the entity + all its direct connections.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Find the entity
        entity = await conn.fetchrow("""
            SELECT * FROM public.bh_entities
            WHERE LOWER(name) = LOWER($1) AND is_active = true
            LIMIT 1
        """, entity_name.strip())

        if not entity:
            return {"found": False, "query": entity_name}

        # Get all relationships (both directions)
        relationships = await conn.fetch("""
            SELECT r.*, 
                   fe.name as from_name, fe.entity_type as from_type,
                   te.name as to_name, te.entity_type as to_type
            FROM public.bh_relationships r
            JOIN public.bh_entities fe ON fe.id = r.from_entity_id
            JOIN public.bh_entities te ON te.id = r.to_entity_id
            WHERE (r.from_entity_id = $1 OR r.to_entity_id = $1)
              AND r.is_active = true
            ORDER BY r.created_at DESC
        """, entity["id"])

    return {
        "found": True,
        "entity": dict(entity),
        "relationships": [dict(r) for r in relationships],
    }


async def recall_graph(query: str, limit: int = 15, user_id: Optional[int] = None) -> dict:
    """
    Hybrid (vector + full-text) search across the entire knowledge graph.
    Returns matching entities with their connections.

    `user_id` is the viewer: entity results are scoped to shared facts plus the
    viewer's own private facts (privacy boundary, migration 0057). None = a
    system caller with no viewer → shared facts only.

    Satisfies R3.2, R3.3.
    """
    retriever = _get_hybrid_retriever()
    if retriever:
        # Hybrid retrieval (R3.2)
        rows = await retriever.search_hybrid(
            query=query,
            source_type='entity',
            limit=limit,
            viewer_user_id=user_id,
        )
        
        if not rows:
            return {"found": False, "query": query, "entities": [], "_display": f"No knowledge found for **{query}**. Try `/remember` to teach me something."}

        # Format rows to look like the legacy entities query result
        entities = []
        for r in rows:
            # Reconstruct the entity dict from the flat result
            # Hybrid search returns {source_id, rrf_score, name, summary, is_active}
            entities.append({
                "id": r["source_id"],
                "name": r["name"],
                "summary": r["summary"],
                "is_active": r["is_active"],
                "rank": r["rrf_score"]
            })
    else:
        # Fallback to legacy full-text search (R3.3)
        pool = get_pool()
        async with pool.acquire() as conn:
            entities = await conn.fetch("""
                SELECT e.*,
                       ts_rank(to_tsvector('english', e.name || ' ' || COALESCE(e.summary, '')),
                               plainto_tsquery('english', $1)) as rank
                FROM public.bh_entities e
                WHERE e.is_active = true
                  AND (e.visibility = 'shared'
                       OR ($3::int IS NOT NULL AND e.created_by = $3::int))
                  AND (
                      to_tsvector('english', e.name || ' ' || COALESCE(e.summary, '')) @@ plainto_tsquery('english', $1)
                      OR LOWER(e.name) LIKE '%' || LOWER($1) || '%'
                      OR e.attributes::text ILIKE '%' || $1 || '%'
                  )
                ORDER BY rank DESC, e.updated_at DESC
                LIMIT $2
            """, query, limit, user_id)

    if not entities:
        return {"found": False, "query": query, "entities": [], "_display": f"No knowledge found for **{query}**. Try `/remember` to teach me something."}

    # For each entity, get its immediate relationships
    pool = get_pool()
    async with pool.acquire() as conn:
        results = []
        for e in entities:
            rels = await conn.fetch("""
                SELECT r.relationship,
                       CASE WHEN r.from_entity_id = $1 THEN te.name ELSE fe.name END as connected_to,
                       CASE WHEN r.from_entity_id = $1 THEN te.entity_type ELSE fe.entity_type END as connected_type,
                       CASE WHEN r.from_entity_id = $1 THEN 'outgoing' ELSE 'incoming' END as direction
                FROM public.bh_relationships r
                JOIN public.bh_entities fe ON fe.id = r.from_entity_id
                JOIN public.bh_entities te ON te.id = r.to_entity_id
                WHERE (r.from_entity_id = $1 OR r.to_entity_id = $1) AND r.is_active = true
                LIMIT 10
            """, e["id"])
            
            # If we don't have the full entity row (hybrid path), fetch it now
            if "entity_type" not in e:
                full_entity = await conn.fetchrow("SELECT * FROM public.bh_entities WHERE id = $1", e["id"])
                e_dict = dict(full_entity) if full_entity else e
            else:
                e_dict = dict(e)
                
            results.append({
                "entity": e_dict,
                "connections": [dict(r) for r in rels],
            })

    # Format display
    display = _format_graph_results(query, results)
    return {"found": True, "query": query, "entities": results, "_display": display}


def _format_graph_results(query: str, results: list) -> str:
    """Format knowledge graph results for chat display."""
    lines = [f"## 🧠 Knowledge: {query}", ""]

    for item in results:
        e = item["entity"]
        connections = item["connections"]

        # Entity header
        type_emoji = {
            "person": "👤", "place": "📍", "thing": "📦", "fact": "💡",
            "event": "📅", "preference": "❤️", "recipe": "🍳", "tool": "🔧",
            "concept": "💭", "note": "📝",
        }.get(e["entity_type"], "•")

        lines.append(f"**{type_emoji} {e['name']}** ({e['entity_type']})")
        if e.get("summary"):
            lines.append(f"  {e['summary']}")

        # Show key attributes
        attrs = e.get("attributes") or {}
        if attrs:
            attr_strs = [f"{k}: {v}" for k, v in list(attrs.items())[:5] if v]
            if attr_strs:
                lines.append(f"  *{', '.join(attr_strs)}*")

        # Show connections
        if connections:
            for c in connections[:5]:
                direction = "→" if c["direction"] == "outgoing" else "←"
                lines.append(f"  {direction} {c['relationship']} → **{c['connected_to']}** ({c['connected_type']})")

        lines.append("")

    return "\n".join(lines)


# ---- Stats -------------------------------------------------------------------

async def get_stats() -> dict:
    """Get knowledge graph statistics."""
    pool = get_pool()
    async with pool.acquire() as conn:
        entity_count = await conn.fetchval("SELECT COUNT(*) FROM public.bh_entities WHERE is_active = true")
        rel_count = await conn.fetchval("SELECT COUNT(*) FROM public.bh_relationships WHERE is_active = true")
        types = await conn.fetch("""
            SELECT entity_type, COUNT(*) as count
            FROM public.bh_entities WHERE is_active = true
            GROUP BY entity_type ORDER BY count DESC
        """)

    return {
        "entities": entity_count,
        "relationships": rel_count,
        "types": {r["entity_type"]: r["count"] for r in types},
    }
