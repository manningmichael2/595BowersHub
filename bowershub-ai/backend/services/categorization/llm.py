"""LLMFallback — tier 4 (R2.4), residue only.

Runs only on transactions unresolved by tiers 0–3 (R5.3). The model is resolved
via `resolve_role("categorizer")` — a DB role defaulting to a LOCAL Ollama model
(privacy-first, R2.4); no literal model id here. Reuses the structured-prompt
scaffolding minus the hardcoded rules block (those are now DB-driven tiers) and
minus the Other-fallback.

Confidence is the model's self-reported score mapped to [0,1]. Parse-failure,
Ollama-down, or timeout ⇒ **abstain → the row goes to the review queue, never
"Other"** (R5.5). The model call is injectable so the tier is testable without a
live Ollama.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Awaitable, Callable, Dict, Optional

import httpx

from ...http_client import get_http_client
from ..model_catalog import resolve_role
from .base import Decision, TxnContext

logger = logging.getLogger(__name__)

OLLAMA_URL = "http://ollama:11434"

# call_model(prompt) -> raw response text, or None on failure (Ollama down/timeout).
CallModel = Callable[[str], Awaitable[Optional[str]]]


async def _default_call_model(prompt: str) -> Optional[str]:
    """Call the local categorizer model. Returns text or None on any failure."""
    model = resolve_role("categorizer")
    try:
        client = get_http_client()
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "messages": [
                    {"role": "system",
                     "content": "You classify bank transactions. Return ONLY the JSON object requested."},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                "options": {"temperature": 0, "num_predict": 256},
            },
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")
    except (httpx.HTTPError, Exception) as e:  # noqa: BLE001 — any failure → abstain
        logger.warning("LLMFallback: model call failed (%s) → abstain", e)
        return None


def _parse(content: str, leaves: Dict[str, int]) -> Optional[tuple[int, float]]:
    """Parse a {"category","confidence"} object. Returns (category_id, confidence)
    or None — None means abstain (parse failure or unknown category, never Other)."""
    if not content:
        return None
    clean = content.strip()
    if clean.startswith("```"):
        clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    match = re.search(r"\{[\s\S]*\}", clean)
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    name = obj.get("category")
    cat_id = leaves.get(name) if isinstance(name, str) else None
    if cat_id is None:                      # unknown category → abstain (never "Other")
        return None
    try:
        conf = float(obj.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    return cat_id, max(0.0, min(1.0, conf))


class LLMFallback:
    tier = "llm"

    def __init__(self, leaves: Dict[str, int], *, call_model: Optional[CallModel] = None,
                 model_id: Optional[str] = None):
        self._leaves = leaves
        self._tree = sorted(leaves.keys())
        self._call_model = call_model or _default_call_model
        # Recorded in provenance + used by the eval harness's per-model accuracy.
        self._model_id = model_id or resolve_role("categorizer")

    def _prompt(self, ctx: TxnContext) -> str:
        return (
            "Categorize this bank transaction. Choose the MOST specific leaf category "
            "from this list (use the leaf name exactly):\n\n"
            + "\n".join(self._tree)
            + "\n\nReturn ONLY a JSON object, no markdown, no explanation:\n"
            '{"category":"<leaf_name>","confidence":<0..1>}\n\n'
            "Transaction: "
            + json.dumps({"description": ctx.description or "", "amount": ctx.amount})
        )

    async def classify(self, ctx: TxnContext) -> Decision:
        raw = await self._call_model(self._prompt(ctx))
        if raw is None:
            return Decision.abstain(self.tier, rationale={"reason": "model_unavailable"})
        parsed = _parse(raw, self._leaves)
        if parsed is None:
            return Decision.abstain(self.tier, rationale={"reason": "parse_failure_or_unknown"})
        cat_id, conf = parsed
        return Decision(category_id=cat_id, confidence=conf, tier=self.tier,
                        rationale={"model_id": self._model_id})


async def load_leaf_categories(conn) -> Dict[str, int]:
    """Leaf category name → id (the LLM only picks leaves, mirroring the legacy prompt)."""
    rows = await conn.fetch("SELECT id, name, parent_id FROM finance.categories")
    child_parents = {r["parent_id"] for r in rows if r["parent_id"] is not None}
    return {r["name"]: r["id"] for r in rows if r["id"] not in child_parents}


async def build_llm_tier(conn, **kwargs) -> LLMFallback:
    return LLMFallback(await load_leaf_categories(conn), **kwargs)
