"""
Local Intelligence Service — Ollama-powered thinking step.

Uses the local Llama 3.2 3B model (zero cost, ~1-2s latency) to:
1. Interpret ambiguous user queries into structured params
2. Refine L2 classifications when confidence is borderline
3. Extract intent from natural language before hitting APIs
4. Resolve follow-up questions using conversation context

This is NOT a replacement for Haiku/Sonnet — it's a cheap pre-processor
that reduces unnecessary L3 escalations and improves skill dispatch accuracy.
"""
import json
from backend.services.model_catalog import resolve_role
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")


async def _call_ollama(prompt: str, max_tokens: int = 150, temperature: float = 0.1) -> Optional[str]:
    """Make a raw call to Ollama. Returns the response text or None on failure."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/generate",
                json={
                    "model": resolve_role("local"),
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("response", "").strip()
    except Exception as e:
        logger.debug(f"Ollama call failed (non-critical): {e}")
        return None


async def interpret_sports_query(query: str) -> Optional[dict]:
    """
    Interpret an ambiguous sports query into structured {league, team} params.
    Used when hardcoded lookups fail.
    
    Returns: {"league": "mlb", "team": "tigers"} or None
    """
    prompt = f"""You are a sports query interpreter. Extract the league and/or team from this query.

Available leagues (use these exact keys): mlb, nfl, nba, nhl, wnba, mls, premier league, la liga, bundesliga, serie a, champions league, ufc, f1, golf, tennis, college football, college basketball

If the sport/league isn't in the list above, set league to null.
If you can identify the team, use their common nickname (e.g. "tigers" not "Detroit Tigers").

Respond with ONLY valid JSON: {{"league": "<key or null>", "team": "<nickname or null>"}}

Query: "{query}"
JSON:"""

    text = await _call_ollama(prompt, max_tokens=60)
    if not text:
        return None
    try:
        # Clean markdown wrapping if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        if isinstance(result, dict):
            logger.info(f"Local intelligence (sports): {query!r} → {result}")
            return result
    except (json.JSONDecodeError, IndexError):
        pass
    return None


async def interpret_news_query(query: str) -> Optional[dict]:
    """
    Interpret a news-related query into structured params.
    
    Returns: {"category": "tech", "topic": "AI"} or None
    """
    prompt = f"""You are a query interpreter for a news headlines skill. Determine what category of news the user wants.

Available categories: top (general/breaking news), sports (ESPN), tech (technology), world (international), business (finance/economy)

Respond with ONLY valid JSON: {{"category": "<category>", "topic": "<specific topic or null>"}}

Query: "{query}"
JSON:"""

    text = await _call_ollama(prompt, max_tokens=50)
    if not text:
        return None
    try:
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        if isinstance(result, dict):
            logger.info(f"Local intelligence (news): {query!r} → {result}")
            return result
    except (json.JSONDecodeError, IndexError):
        pass
    return None


async def refine_classification(
    message: str,
    haiku_skill: Optional[str],
    haiku_confidence: float,
    available_skills: list[dict],
) -> Optional[dict]:
    """
    When Haiku's L2 classification is borderline (0.5-0.75 confidence),
    use the local model to either confirm or override the classification.
    
    This catches cases where Haiku is uncertain but the answer is obvious
    to a model that can reason about the available skills.
    
    Returns: {"skill": "name", "confidence": 0.8, "params": {...}} or None to accept Haiku's answer
    """
    skills_desc = "\n".join(f"- {s['name']}: {s['description']}" for s in available_skills[:15])

    prompt = f"""A classifier identified the user's message as needing the "{haiku_skill}" skill with {haiku_confidence:.0%} confidence.

Available skills:
{skills_desc}

User message: "{message}"

Is "{haiku_skill}" the right skill? If yes, extract the parameters. If a different skill is better, suggest it.
Respond with ONLY valid JSON: {{"skill": "<skill_name>", "confidence": <0.0-1.0>, "params": {{<key-value params>}}}}
JSON:"""

    text = await _call_ollama(prompt, max_tokens=100)
    if not text:
        return None
    try:
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        if isinstance(result, dict) and result.get("skill"):
            logger.info(f"Local intelligence (refine): confirmed={result['skill']} conf={result.get('confidence')}")
            return result
    except (json.JSONDecodeError, IndexError):
        pass
    return None


async def extract_skill_params(message: str, skill_name: str, skill_description: str) -> Optional[dict]:
    """
    Given a message and a known target skill, extract the best parameters.
    Used when L2 identifies the skill but param extraction is tricky.
    
    Returns: {"param_name": "value", ...} or None
    """
    prompt = f"""Extract parameters for the "{skill_name}" skill from this user message.

Skill description: {skill_description}

User message: "{message}"

Extract relevant parameters as JSON. Common patterns:
- Sports: {{"team": "tigers"}} or {{"sport": "mlb"}}
- Weather: {{"location": "Detroit"}}
- News: {{"category": "tech"}}
- Finance: {{"question": "how much did I spend on groceries"}}
- Knowledge: {{"query": "router bits"}}

Respond with ONLY valid JSON (the params object):"""

    text = await _call_ollama(prompt, max_tokens=80)
    if not text:
        return None
    try:
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        if isinstance(result, dict):
            logger.info(f"Local intelligence (params): {skill_name} → {result}")
            return result
    except (json.JSONDecodeError, IndexError):
        pass
    return None


async def should_escalate_to_l3(message: str, skill_result: str) -> bool:
    """
    After a skill returns a result, check if the result actually answers
    the user's question. If not, recommend escalation to L3.
    
    This prevents cases where a skill returns data but doesn't answer
    what the user actually asked (e.g., they asked "who is pitching"
    and got a score with no pitcher info).
    
    Returns: True if L3 escalation is recommended, False if skill result is sufficient.
    """
    prompt = f"""Does this skill result answer the user's question?

User asked: "{message}"
Skill returned: "{skill_result[:500]}"

If the result contains the information the user asked for, respond "yes".
If the result is missing key information or doesn't answer the question, respond "no".

Answer (yes/no):"""

    text = await _call_ollama(prompt, max_tokens=10)
    if not text:
        return False  # Default: don't escalate
    return text.lower().strip().startswith("no")


async def is_available() -> bool:
    """Check if Ollama is reachable and has the model loaded."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{OLLAMA_URL}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return any(resolve_role("local").split(":")[0] in m for m in models)
    except Exception:
        pass
    return False
