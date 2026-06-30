"""Native skill: recall and remember (knowledge base).

Dual-path: writes to both the markdown knowledge base (legacy) and the
knowledge graph (structured). Recall searches both and merges results.
"""

from backend.services.skill_registry import native_skill


@native_skill("recall")
async def handle_recall(params: dict) -> dict:
    from backend.services.knowledge import recall
    from backend.services.knowledge_graph import recall_graph

    query = params.get("query") or params.get("question") or params.get("q", "")
    if not query:
        return {"_display": "What would you like me to search for?"}

    # The viewer (injected by skill_executor as _user_id) scopes graph recall to
    # shared facts + this user's own private facts (privacy boundary, 0057).
    user_id = params.get("_user_id")

    # Search both systems in parallel
    import asyncio
    markdown_result, graph_result = await asyncio.gather(
        recall(query=query),
        recall_graph(query=query, user_id=user_id),
        return_exceptions=True,
    )

    # If graph found results, prefer its formatted output
    if isinstance(graph_result, dict) and graph_result.get("found"):
        return graph_result

    # Fall back to markdown results
    if isinstance(markdown_result, dict):
        return markdown_result

    return {"_display": f"No knowledge found for **{query}**. Try `/remember` to teach me something."}


@native_skill("remember")
async def handle_remember(params: dict) -> dict:
    from backend.services.knowledge import remember
    from backend.services.knowledge_graph import remember_entity

    topic = params.get("topic", "")
    fact = params.get("fact", "")

    if not fact and not topic:
        return {"_display": "Tell me what to remember. Example: `/remember cooking Manon is allergic to shellfish`"}

    # Write to markdown (legacy path — still works for grep-based recall)
    markdown_result = await remember(topic=topic, fact=fact)

    # Also write to knowledge graph as a structured entity
    try:
        # Determine entity type from topic
        type_map = {
            "cooking": "preference", "finance": "fact", "woodshop": "fact",
            "house": "fact", "people": "person", "household": "fact",
        }
        entity_type = type_map.get(topic.split("/")[0] if "/" in topic else topic, "note")

        # Create an entity for this fact
        entity_name = topic.replace("/", " — ") if topic else "general note"
        await remember_entity(
            name=entity_name,
            entity_type=entity_type,
            summary=fact,
            attributes={"topic": topic, "raw_fact": fact},
            source="chat",
        )
    except Exception:
        pass  # Graph write failure is non-critical — markdown is the fallback

    return markdown_result
