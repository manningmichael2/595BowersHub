"""
Universal Toolbox — Flexible API execution layer available to all routing layers.

This is NOT a hardcoded skill system. It's a dynamic, growing toolbox that:
1. Maintains a registry of known APIs (DB-driven, not code)
2. Executes HTTP requests safely with logging
3. Lets any model (Ollama, Haiku, Sonnet) discover and use APIs
4. Learns from usage — frequently-called APIs get optimized over time
5. Can discover NEW APIs via web search when it doesn't know how to answer something

Architecture:
- Registry: bh_api_registry table (name, base_url, description, auth_type, endpoints JSONB)
- Executor: Generic HTTP caller with response parsing + formatting
- Discovery: Haiku/Sonnet can search for APIs and register them
- Logging: Every call logged to bh_api_usage_log for pattern detection

Available to: L1 (slash commands), L2 (Haiku tool-use), L3 (Sonnet tool-use)
"""
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import urlencode, urljoin

import httpx

from backend.database import get_pool

logger = logging.getLogger(__name__)

# Safety limits
MAX_RESPONSE_SIZE = 100_000  # 100KB max response body
REQUEST_TIMEOUT = 15.0
MAX_CHAIN_DEPTH = 3  # Max sequential API calls per query


# ---- Registry Operations ----------------------------------------------------

async def get_registry() -> list[dict]:
    """Get all registered APIs from the database."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, base_url, description, auth_type, auth_config,
                   endpoints, headers, is_active, usage_count, last_used_at
            FROM public.bh_api_registry
            WHERE is_active = true
            ORDER BY usage_count DESC
        """)
    return [dict(r) for r in rows]


async def get_registry_summary() -> str:
    """Get a concise summary of available APIs for prompt injection."""
    apis = await get_registry()
    if not apis:
        return "No APIs registered yet."

    lines = []
    for api in apis:
        endpoints = api.get("endpoints") or []
        endpoint_desc = ""
        if isinstance(endpoints, list) and endpoints:
            ep_names = [ep.get("name", ep.get("path", "")) for ep in endpoints[:5]]
            endpoint_desc = f" (endpoints: {', '.join(ep_names)})"
        lines.append(f"- **{api['name']}**: {api['description']}{endpoint_desc}")

    return "\n".join(lines)


async def register_api(
    name: str,
    base_url: str,
    description: str,
    endpoints: list[dict],
    auth_type: str = "none",
    auth_config: Optional[dict] = None,
    headers: Optional[dict] = None,
) -> int:
    """
    Register a new API in the toolbox. Returns the new API id.

    endpoints format:
    [
        {
            "name": "get_scores",
            "path": "/scoreboard",
            "method": "GET",
            "description": "Get today's scores for a league",
            "params": {"dates": "YYYYMMDD format date"}
        },
        ...
    ]
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            INSERT INTO public.bh_api_registry (name, base_url, description, auth_type, auth_config, endpoints, headers)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb)
            ON CONFLICT (name) DO UPDATE SET
                base_url = EXCLUDED.base_url,
                description = EXCLUDED.description,
                endpoints = EXCLUDED.endpoints,
                headers = EXCLUDED.headers,
                auth_type = EXCLUDED.auth_type,
                auth_config = EXCLUDED.auth_config,
                is_active = true
            RETURNING id
        """, name, base_url, description, auth_type,
            json.dumps(auth_config) if auth_config else None,
            json.dumps(endpoints),
            json.dumps(headers) if headers else None,
        )
    logger.info(f"Registered API: {name} ({base_url})")
    return row["id"]


# ---- HTTP Executor -----------------------------------------------------------

async def execute_api_call(
    url: str,
    method: str = "GET",
    params: Optional[dict] = None,
    body: Optional[dict] = None,
    headers: Optional[dict] = None,
    api_name: Optional[str] = None,
) -> dict:
    """
    Execute an HTTP request safely. Returns structured result.

    This is the core executor — any layer can call it.
    All calls are logged for pattern detection.

    Returns:
        {
            "ok": True/False,
            "status": 200,
            "data": <parsed JSON or text>,
            "duration_ms": 142,
            "content_type": "application/json"
        }
    """
    start = time.time()

    # Safety: block internal network requests
    if _is_internal_url(url):
        return {"ok": False, "error": "Cannot call internal/private URLs", "status": 0}

    try:
        req_headers = {"User-Agent": "BowersHub-AI/1.0"}
        if headers:
            req_headers.update(headers)

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT, follow_redirects=True) as client:
            if method.upper() == "GET":
                resp = await client.get(url, params=params, headers=req_headers)
            elif method.upper() == "POST":
                resp = await client.post(url, json=body, params=params, headers=req_headers)
            else:
                resp = await client.request(method.upper(), url, json=body, params=params, headers=req_headers)

        duration_ms = int((time.time() - start) * 1000)

        # Parse response
        content_type = resp.headers.get("content-type", "")
        if len(resp.content) > MAX_RESPONSE_SIZE:
            return {
                "ok": False,
                "error": f"Response too large ({len(resp.content)} bytes, max {MAX_RESPONSE_SIZE})",
                "status": resp.status_code,
                "duration_ms": duration_ms,
            }

        if "json" in content_type or resp.text.strip().startswith(("{", "[")):
            try:
                data = resp.json()
            except (json.JSONDecodeError, ValueError):
                data = resp.text[:5000]
        else:
            data = resp.text[:5000]

        result = {
            "ok": 200 <= resp.status_code < 400,
            "status": resp.status_code,
            "data": data,
            "duration_ms": duration_ms,
            "content_type": content_type,
        }

        # Log the usage
        await _log_usage(api_name or _extract_domain(url), url, method, resp.status_code, duration_ms)

        return result

    except httpx.TimeoutException:
        return {"ok": False, "error": "Request timed out", "status": 0, "duration_ms": int((time.time() - start) * 1000)}
    except Exception as e:
        return {"ok": False, "error": str(e), "status": 0, "duration_ms": int((time.time() - start) * 1000)}


# ---- Built-in Tools (no API needed) -----------------------------------------

def calculate(expression: str) -> dict:
    """
    Safe math evaluation using simpleeval (no arbitrary code execution).
    Handles percentages, tips, basic arithmetic.
    Available to all layers without any API call.
    """
    import math
    from simpleeval import simple_eval, InvalidExpression

    expression_clean = expression.lower().strip()

    # Handle percentage phrases
    expression_clean = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*of\s*(\d+(?:\.\d+)?)", r"(\1/100)*\2", expression_clean)
    expression_clean = re.sub(r"(\d+(?:\.\d+)?)\s*%\s*tip\s*(?:on\s*)?(\d+(?:\.\d+)?)", r"(\1/100)*\2", expression_clean)

    # Replace common words
    expression_clean = expression_clean.replace("plus", "+").replace("minus", "-")
    expression_clean = expression_clean.replace("times", "*").replace("divided by", "/")
    expression_clean = expression_clean.replace("x", "*").replace("×", "*").replace("÷", "/")
    expression_clean = expression_clean.replace("^", "**")

    # Strip non-math characters but keep decimal points, parens, operators
    safe_expr = re.sub(r"[^0-9.+\-*/()%\s]", "", expression_clean)
    safe_expr = safe_expr.replace("%", "/100")

    if not safe_expr.strip():
        return {"error": "Couldn't parse that as a math expression.", "_display": f"I couldn't evaluate: *{expression}*"}

    try:
        # simpleeval: safe expression evaluation with no access to builtins, imports, or attributes
        result = simple_eval(safe_expr, functions={"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt})
        # Format nicely
        if isinstance(result, float):
            if result == int(result) and abs(result) < 1e15:
                formatted = str(int(result))
            else:
                formatted = f"{result:.2f}"
        else:
            formatted = str(result)

        return {
            "expression": expression,
            "result": formatted,
            "_display": f"**{expression}** = **{formatted}**",
        }
    except (InvalidExpression, TypeError, ValueError, ZeroDivisionError) as e:
        return {"error": str(e), "_display": f"Couldn't calculate: *{expression}*"}
    except Exception as e:
        return {"error": str(e), "_display": f"Couldn't calculate: *{expression}*"}


UNIT_CONVERSIONS = {
    # Length
    ("miles", "km"): 1.60934, ("km", "miles"): 0.621371,
    ("feet", "meters"): 0.3048, ("meters", "feet"): 3.28084,
    ("inches", "cm"): 2.54, ("cm", "inches"): 0.393701,
    ("yards", "meters"): 0.9144, ("meters", "yards"): 1.09361,
    # Weight
    ("lbs", "kg"): 0.453592, ("kg", "lbs"): 2.20462,
    ("oz", "grams"): 28.3495, ("grams", "oz"): 0.035274,
    ("pounds", "kg"): 0.453592, ("kg", "pounds"): 2.20462,
    # Volume
    ("gallons", "liters"): 3.78541, ("liters", "gallons"): 0.264172,
    ("cups", "ml"): 236.588, ("ml", "cups"): 0.00422675,
    ("cups", "liters"): 0.236588, ("liters", "cups"): 4.22675,
    ("tbsp", "ml"): 14.7868, ("ml", "tbsp"): 0.067628,
    ("tsp", "ml"): 4.92892, ("ml", "tsp"): 0.202884,
    ("fl oz", "ml"): 29.5735, ("ml", "fl oz"): 0.033814,
    # Temperature (handled separately)
    ("f", "c"): "special", ("c", "f"): "special",
    ("fahrenheit", "celsius"): "special", ("celsius", "fahrenheit"): "special",
}

# Aliases
UNIT_ALIASES = {
    "kilometer": "km", "kilometers": "km", "kilometre": "km",
    "meter": "meters", "metre": "meters", "metres": "meters",
    "centimeter": "cm", "centimeters": "cm",
    "inch": "inches", "in": "inches",
    "foot": "feet", "ft": "feet",
    "yard": "yards", "yd": "yards",
    "mile": "miles", "mi": "miles",
    "pound": "pounds", "lb": "lbs",
    "ounce": "oz", "ounces": "oz",
    "gram": "grams", "g": "grams",
    "kilogram": "kg", "kilograms": "kg",
    "liter": "liters", "litre": "liters", "litres": "liters", "l": "liters",
    "gallon": "gallons", "gal": "gallons",
    "cup": "cups",
    "tablespoon": "tbsp", "tablespoons": "tbsp",
    "teaspoon": "tsp", "teaspoons": "tsp",
    "milliliter": "ml", "milliliters": "ml", "millilitre": "ml",
}


def convert_units(value: float, from_unit: str, to_unit: str) -> dict:
    """Convert between units. Available to all layers."""
    from_u = UNIT_ALIASES.get(from_unit.lower().strip(), from_unit.lower().strip())
    to_u = UNIT_ALIASES.get(to_unit.lower().strip(), to_unit.lower().strip())

    # Temperature special case
    if (from_u, to_u) in [("f", "c"), ("fahrenheit", "celsius")]:
        result = (value - 32) * 5 / 9
        return {"result": f"{result:.1f}", "_display": f"**{value}°F** = **{result:.1f}°C**"}
    elif (from_u, to_u) in [("c", "f"), ("celsius", "fahrenheit")]:
        result = value * 9 / 5 + 32
        return {"result": f"{result:.1f}", "_display": f"**{value}°C** = **{result:.1f}°F**"}

    factor = UNIT_CONVERSIONS.get((from_u, to_u))
    if factor and factor != "special":
        result = value * factor
        if result == int(result):
            formatted = str(int(result))
        else:
            formatted = f"{result:.4f}".rstrip("0").rstrip(".")
        return {
            "result": formatted,
            "_display": f"**{value} {from_unit}** = **{formatted} {to_unit}**",
        }

    return {
        "error": f"Don't know how to convert {from_unit} to {to_unit}.",
        "_display": f"I can't convert {from_unit} to {to_unit}. Try common units like miles/km, lbs/kg, cups/liters, °F/°C.",
    }


# ---- Usage Logging -----------------------------------------------------------

async def _log_usage(api_name: str, url: str, method: str, status: int, duration_ms: int):
    """Log an API call for pattern detection."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO public.bh_api_usage_log (api_name, url, method, status_code, duration_ms, called_at)
                VALUES ($1, $2, $3, $4, $5, NOW())
            """, api_name, url[:500], method, status, duration_ms)

            # Update registry usage count
            await conn.execute("""
                UPDATE public.bh_api_registry
                SET usage_count = usage_count + 1, last_used_at = NOW()
                WHERE name = $1
            """, api_name)
    except Exception as e:
        # Non-critical — don't fail the request
        logger.debug(f"Usage logging failed: {e}")


async def get_usage_stats(days: int = 7) -> list[dict]:
    """Get API usage stats for the last N days."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT api_name, COUNT(*) as calls,
                   AVG(duration_ms)::int as avg_ms,
                   MAX(called_at) as last_call
            FROM public.bh_api_usage_log
            WHERE called_at > NOW() - INTERVAL '1 day' * $1
            GROUP BY api_name
            ORDER BY calls DESC
            LIMIT 20
        """, days)
    return [dict(r) for r in rows]


# ---- Safety ------------------------------------------------------------------

def _is_internal_url(url: str) -> bool:
    """Block requests to internal/private networks."""
    blocked_patterns = [
        "localhost", "127.0.0.1", "0.0.0.0",
        "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.",
        "192.168.", "169.254.",
        ".internal", ".local",
    ]
    url_lower = url.lower()
    # Allow our own services (filewriter, ollama) explicitly
    allowed_internal = ["ollama", "filewriter", "postgres"]
    for allowed in allowed_internal:
        if allowed in url_lower:
            return False
    for pattern in blocked_patterns:
        if pattern in url_lower:
            return True
    return False


def _extract_domain(url: str) -> str:
    """Extract domain name from URL for logging."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]
    except Exception:
        return "unknown"
