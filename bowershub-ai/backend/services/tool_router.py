"""
Tool Router — Flexible L2 tool-use layer.

Instead of classifying to a pre-built skill, Haiku sees the API registry
and built-in tools, then decides what to call and how. This replaces the
rigid "classify → dispatch to hardcoded skill" pattern.

The same tool router is available to L1, L2, and L3:
- L1: Slash commands can invoke it directly (/api, /calc, /convert)
- L2: Haiku uses it for queries it can handle via API calls
- L3: Sonnet uses the same registry for its tool-use loop

Key principle: Adding a new capability = registering an API in the DB.
No code changes needed.
"""
import json
from backend.services.model_catalog import resolve_role
import logging
from typing import Optional

import httpx

from backend.database import get_pool
from backend.services.toolbox import (
    calculate,
    convert_units,
    execute_api_call,
    get_registry,
    get_registry_summary,
    register_api,
)

logger = logging.getLogger(__name__)

# Model ID from config — single source of truth
def _get_haiku_model() -> str:
    """Get the Haiku model ID. Reads from env or uses default."""
    import os
    return resolve_role("fast")

logger = logging.getLogger(__name__)

# The prompt that turns Haiku into a flexible tool-user
TOOL_USE_PROMPT = """You are a tool-use assistant. Given a user's question and a list of available tools/APIs, decide what to do.

## Available Built-in Tools (instant, no API call):
- **calculate**: Evaluate math expressions, percentages, tips. Example: calculate("15% of 87") → 13.05
- **convert**: Unit conversions. Example: convert(3, "cups", "liters") → 0.71
- **none_needed**: The question doesn't need any tool — it's general knowledge you can answer directly.

## Available APIs:
{api_registry}

## Instructions:
1. If you can answer directly from your knowledge (simple facts, definitions, opinions), use "none_needed" and provide the answer.
2. If a built-in tool handles it (math, conversions), use that.
3. If an API can answer it, construct the API call. You may need to chain calls (e.g., get game ID from scoreboard, then get box score from summary).
4. If nothing in the registry can help, say "no_tool" — the query will escalate to a more capable model.

## Response Format (ONLY valid JSON, no explanation):
{{
    "action": "api_call" | "calculate" | "convert" | "direct_answer" | "no_tool",
    "reasoning": "<one sentence about why this action>",
    
    // For api_call:
    "api": "<api name from registry>",
    "calls": [
        {{"url": "<full URL with path params filled in>", "method": "GET", "params": {{}}}}
    ],
    
    // For calculate:
    "expression": "<math expression>",
    
    // For convert:
    "value": <number>, "from": "<unit>", "to": "<unit>",
    
    // For direct_answer:
    "answer": "<your answer in markdown>"
}}

## User's question: "{message}"
"""


async def route_with_tools(message: str, conversation_context: str = "") -> Optional[dict]:
    """
    Use Haiku to flexibly handle a query using the API registry and built-in tools.
    
    Returns:
        {"content": "formatted response", "layer": "L2", "cost": 0.002}
        or None if it can't handle the query (escalate to L3)
    """
    from backend.services.model_provider import get_provider

    # Get the API registry for the prompt
    registry_summary = await get_registry_summary()

    prompt = TOOL_USE_PROMPT.format(
        api_registry=registry_summary,
        message=message,
    )

    # Add conversation context if available
    if conversation_context:
        prompt += f"\n\n## Recent conversation context:\n{conversation_context}"

    try:
        provider = get_provider()
        result = await provider.complete(
            model=_get_haiku_model(),
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )

        content = result.content.strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        decision = json.loads(content)
        action = decision.get("action", "no_tool")

        logger.info(f"Tool router decision: action={action}, reasoning={decision.get('reasoning', '')[:80]}")

        if action == "no_tool":
            return None  # Escalate to L3

        if action == "direct_answer":
            answer = decision.get("answer", "")
            if answer:
                return {
                    "content": answer,
                    "model_used": _get_haiku_model(),
                    "input_tokens": result.input_tokens,
                    "output_tokens": result.output_tokens,
                }
            return None

        if action == "calculate":
            expr = decision.get("expression", "")
            if expr:
                calc_result = calculate(expr)
                return {"content": calc_result.get("_display", str(calc_result))}
            return None

        if action == "convert":
            value = decision.get("value", 0)
            from_unit = decision.get("from", "")
            to_unit = decision.get("to", "")
            if from_unit and to_unit:
                conv_result = convert_units(float(value), from_unit, to_unit)
                return {"content": conv_result.get("_display", str(conv_result))}
            return None

        if action == "api_call":
            calls = decision.get("calls", [])
            if not calls:
                return None

            # Execute the API calls (support chaining)
            all_data = []
            for call in calls[:3]:  # Max 3 chained calls
                url = call.get("url", "")
                method = call.get("method", "GET")
                params = call.get("params")
                api_name = decision.get("api", "unknown")

                if not url:
                    continue

                api_result = await execute_api_call(
                    url=url,
                    method=method,
                    params=params,
                    api_name=api_name,
                )

                if api_result.get("ok"):
                    all_data.append(api_result.get("data"))
                else:
                    all_data.append({"error": api_result.get("error", "Request failed")})

            if not all_data:
                return None

            # Have Haiku format the response nicely
            format_result = await _format_api_response(message, all_data, provider)
            if format_result:
                return {
                    "content": format_result,
                    "model_used": _get_haiku_model(),
                    "input_tokens": result.input_tokens + 200,  # Approximate
                    "output_tokens": result.output_tokens + 100,
                }

            # Fallback: return raw data summary
            return {"content": f"Here's what I found:\n\n```json\n{json.dumps(all_data[0], indent=2)[:2000]}\n```"}

    except json.JSONDecodeError as e:
        logger.warning(f"Tool router JSON parse error: {e}")
        return None
    except Exception as e:
        logger.warning(f"Tool router failed: {e}")
        return None


async def _format_api_response(question: str, data: list, provider) -> Optional[str]:
    """
    Format raw API data into a beautiful, readable response.
    
    Strategy: Try local model first (free) for simple data.
    Fall back to Haiku ($0.001) for complex/large data.
    """
    data_str = json.dumps(data[0] if len(data) == 1 else data, indent=2)
    if len(data_str) > 8000:
        data_str = data_str[:8000] + "\n... (truncated)"

    format_instructions = f"""You are formatting data for a mobile chat app. The user asked: "{question}"

Raw data:
{data_str}

FORMAT RULES:
- Use clean markdown that renders well on mobile (no wide tables — they break on small screens)
- For tabular data (box scores, standings, stats), use monospace code blocks with aligned columns
- For lists (news, scores), use bullet points with bold highlights
- Be concise but complete — include all relevant data
- Use emoji sparingly for visual structure (⚾ 🏈 📰 etc.)
- If the data doesn't answer the question, say so clearly and suggest what to try
- Never show raw JSON to the user
- Format numbers nicely (commas for thousands, 2 decimal places for money)

Present the data:"""

    # Simple data (< 500 chars) → try local model first (free)
    if len(data_str) < 500:
        try:
            from backend.services.local_intelligence import _call_ollama
            local_result = await _call_ollama(format_instructions, max_tokens=400, temperature=0.3)
            if local_result and len(local_result) > 20:
                return local_result
        except Exception:
            pass

    # Complex data or local failed → Haiku (reliable, $0.001)
    try:
        result = await provider.complete(
            model=_get_haiku_model(),
            messages=[{"role": "user", "content": format_instructions}],
            max_tokens=1500,
        )
        return result.content
    except Exception as e:
        logger.warning(f"Response formatting failed: {e}")
        return None


# ---- L3 Tool Definitions (for Sonnet's tool-use loop) -----------------------

def get_l3_tools() -> list[dict]:
    """
    Return tool definitions for Sonnet's tool-use loop at L3.
    These are the same tools available to L2, but described in Anthropic's tool format
    so Sonnet can call them via its native tool-use capability.
    """
    return [
        {
            "name": "http_request",
            "description": (
                "Make an HTTP request to any public API. Use this to fetch live data like "
                "sports scores, weather, news, movie info, exchange rates, etc. "
                "Check the API registry first for known endpoints. "
                "Available APIs include: ESPN (sports), wttr.in (weather), NPR/Ars (news), "
                "Open-Meteo (weather), TMDB (movies/TV), Wikipedia, exchange rates."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Full URL to request"},
                    "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                    "params": {"type": "object", "description": "Query parameters"},
                    "api_name": {"type": "string", "description": "Name of the API (for logging)"},
                },
                "required": ["url"],
            },
        },
        {
            "name": "calculate",
            "description": "Evaluate a math expression. Handles percentages, tips, basic arithmetic.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate"},
                },
                "required": ["expression"],
            },
        },
        {
            "name": "convert_units",
            "description": "Convert between units (miles/km, lbs/kg, cups/liters, °F/°C, etc).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "number", "description": "Value to convert"},
                    "from_unit": {"type": "string", "description": "Source unit"},
                    "to_unit": {"type": "string", "description": "Target unit"},
                },
                "required": ["value", "from_unit", "to_unit"],
            },
        },
        {
            "name": "search_api_registry",
            "description": "Search the registered API list to find what APIs are available and their endpoints.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What kind of data you're looking for"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "knowledge_graph_query",
            "description": (
                "Search the user's personal knowledge graph for stored facts, entities, and relationships. "
                "Use this when the user asks about something they previously told you, personal facts, "
                "preferences, people in their life, or anything from their memory. "
                "Examples: 'What do I know about Manon?', 'What are my woodshop tools?', 'Do I have any allergies noted?'"
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for in the knowledge graph"},
                    "entity_type": {"type": "string", "description": "Optional filter: person, place, thing, fact, preference, recipe, tool, concept"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "knowledge_graph_remember",
            "description": (
                "Store a new fact, entity, or relationship in the user's personal knowledge graph. "
                "Use this when the user shares personal information they want remembered. "
                "Examples: 'Manon is allergic to shellfish', 'I bought a new router table', 'My HSA account is at Fidelity'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Entity name (person, thing, or topic)"},
                    "entity_type": {"type": "string", "description": "Type: person, place, thing, fact, preference, recipe, tool, concept, note"},
                    "summary": {"type": "string", "description": "One-line summary or the fact itself"},
                    "attributes": {"type": "object", "description": "Key-value attributes (optional)"},
                },
                "required": ["name", "entity_type", "summary"],
            },
        },
        {
            "name": "manage_list",
            "description": (
                "Manage shopping lists, to-do lists, packing lists, or any list. "
                "Actions: add items, check off items (bought/done), remove items, view list, clear checked items. "
                "Use when user says things like 'add milk to my shopping list', 'I got the eggs', "
                "'what's on my list?', 'clear my shopping list'."
            ),
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["view", "add", "check", "remove", "clear", "all"], "description": "What to do"},
                    "list_name": {"type": "string", "description": "Which list, if the user named one (e.g. groceries, todo, gifts, packing). Omit it when unsure — the router picks the right existing list."},
                    "items": {"type": "array", "items": {"type": "string"}, "description": "Items to add/check/remove"},
                },
                "required": ["action"],
            },
        },
    ]


async def execute_l3_tool(tool_name: str, tool_input: dict) -> str:
    """Execute a tool call from L3 (Sonnet's tool-use loop)."""
    if tool_name == "http_request":
        result = await execute_api_call(
            url=tool_input.get("url", ""),
            method=tool_input.get("method", "GET"),
            params=tool_input.get("params"),
            api_name=tool_input.get("api_name", "l3_call"),
        )
        if result.get("ok"):
            data = result.get("data")
            if isinstance(data, (dict, list)):
                return json.dumps(data, indent=2)[:5000]
            return str(data)[:5000]
        return f"Error: {result.get('error', 'Request failed')} (status {result.get('status')})"

    elif tool_name == "calculate":
        result = calculate(tool_input.get("expression", ""))
        return result.get("_display", json.dumps(result))

    elif tool_name == "convert_units":
        result = convert_units(
            float(tool_input.get("value", 0)),
            tool_input.get("from_unit", ""),
            tool_input.get("to_unit", ""),
        )
        return result.get("_display", json.dumps(result))

    elif tool_name == "search_api_registry":
        summary = await get_registry_summary()
        return summary

    elif tool_name == "knowledge_graph_query":
        from backend.services.knowledge_graph import recall_graph
        result = await recall_graph(
            query=tool_input.get("query", ""),
            limit=10,
        )
        return result.get("_display", json.dumps(result.get("entities", []), indent=2)[:3000])

    elif tool_name == "knowledge_graph_remember":
        from backend.services.knowledge_graph import remember_entity
        result = await remember_entity(
            name=tool_input.get("name", ""),
            entity_type=tool_input.get("entity_type", "note"),
            summary=tool_input.get("summary", ""),
            attributes=tool_input.get("attributes"),
            source="l3_tool",
        )
        return f"✅ Remembered: {result.get('name', '')} ({result.get('entity_type', '')})"

    elif tool_name == "manage_list":
        from backend.services.lists import get_list, check_items, remove_items, clear_checked, get_all_lists
        from backend.services import list_router
        action = tool_input.get("action", "view")
        list_name = tool_input.get("list_name")          # no hardcoded default
        items = tool_input.get("items", [])
        if action == "add":
            # Route each item to the right existing list (or the default); never
            # auto-creates from a guessed name.
            from backend.services.skills.lists import _format_add
            result = _format_add(await list_router.route_and_add(items, 1, explicit_list=list_name))
        elif action in ("check", "done", "bought"):
            result = await check_items(list_name or "", items)
        elif action == "remove":
            result = await remove_items(list_name or "", items)
        elif action == "clear":
            result = await clear_checked(list_name or "")
        elif action == "all":
            result = await get_all_lists()
        else:
            result = await get_list(list_name or "")
        return result.get("_display", json.dumps(result))

    return f"Unknown tool: {tool_name}"
