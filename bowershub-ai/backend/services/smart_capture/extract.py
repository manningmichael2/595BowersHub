"""Native smart-capture extract (R2.1 / R2.7 / R2.8).

One governed `model_provider.complete(resolve_role("fast"), …)` call, then the
n8n `Parse Classification` behavior reproduced: fence-strip → JSON parse →
`other`-fallback if unparseable. Enforces a max input size (R2.8). Mints the
real HMAC extract_token over every returned intent (each bound to the resolved
asset_id). On model error returns `{ok: False, error}` (drives the overlay
raw-note fallback and a clear inbox error — R2.7).

The image/vision step (process-asset) is resolved by the caller and passed in as
`asset` — extract only classifies. This keeps extract pure/testable and lets the
engine layer gate native-vs-proxied vision (M4).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from backend.services.model_catalog import resolve_role

from .config import get_token_secret
from .intents import DOMAINS, CaptureIntent
from .prompt import SYSTEM_PROMPT, build_user_prompt
from .tokens import mint

logger = logging.getLogger(__name__)

# Guard against abuse / runaway prompts. Capture text is small by nature; a full
# recipe or long note fits comfortably under this. Oversized input is rejected
# (R2.8) rather than silently truncated.
MAX_INPUT_CHARS = 20_000

_FENCE_OPEN = re.compile(r"^```(?:json)?", re.IGNORECASE)
_FENCE_CLOSE = re.compile(r"```\s*$", re.IGNORECASE)


def _strip_fences(raw: str) -> str:
    t = (raw or "").strip()
    t = _FENCE_OPEN.sub("", t).strip()
    t = _FENCE_CLOSE.sub("", t).strip()
    return t


def _other_fallback(text: str, asset: Optional[dict]) -> dict:
    """The n8n unparseable-output fallback: route to `other` so input isn't lost."""
    vision = ""
    if asset and asset.get("ai_summary"):
        vision = f"\n\nVision: {asset['ai_summary']}"
    return {
        "domain": "other",
        "summary": "Unstructured capture (classifier output not parseable)",
        "payload": {
            "suggested_title": (text or "capture")[:60],
            "content": (text or "") + vision,
        },
        "needs_more_info": [],
    }


def _coerce_domain(intent: dict) -> dict:
    """Enforce the DOMAINS allow-list: an out-of-list domain is re-routed to
    `other` (nothing is lost) rather than passed downstream to a committer that
    can't handle it."""
    if intent.get("domain") in DOMAINS:
        return intent
    return {
        "domain": "other",
        "summary": intent.get("summary") or "Unclassified capture",
        "payload": {
            "suggested_title": (intent.get("summary") or "capture")[:60],
            "content": json.dumps(intent.get("payload") or {}, ensure_ascii=False),
        },
        "needs_more_info": intent.get("needs_more_info") or [],
    }


def _parse_intents(raw: str, text: str, asset: Optional[dict]) -> list[dict]:
    stripped = _strip_fences(raw)
    parsed = None
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        parsed = None

    intents = parsed.get("intents") if isinstance(parsed, dict) else None
    if not isinstance(intents, list) or not intents:
        return [_other_fallback(text, asset)]

    coerced = [_coerce_domain(i) for i in intents if isinstance(i, dict)]
    return coerced or [_other_fallback(text, asset)]


async def extract_native(
    *,
    text: Optional[str],
    domain_hint: Optional[str],
    user_id: int,
    workspace_id: int,
    model_provider,
    conn,
    now: float,
    asset: Optional[dict] = None,
) -> dict:
    """Classify a capture into intents and mint an extract token.

    Returns the n8n-compatible extract shape on success:
      {ok, intents:[{domain,summary,payload,needs_more_info}], asset?, raw_text?, extract_token}
    or {ok: False, error} on bad input / model failure.
    """
    text = (text or "").strip()
    asset_id = (asset or {}).get("asset_id")

    if not text and not asset_id:
        return {"ok": False, "error": "Must provide 'text' and/or an image."}
    if len(text) > MAX_INPUT_CHARS:
        return {
            "ok": False,
            "error": f"Input too large ({len(text)} chars; max {MAX_INPUT_CHARS}). "
            "Split it into smaller captures.",
        }

    user_prompt = build_user_prompt(text, domain_hint, asset)
    model = resolve_role("fast")
    try:
        result = await model_provider.complete(
            model=model,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=2048,
            system=SYSTEM_PROMPT,
        )
    except Exception as e:  # model/provider failure → clear error (R2.7)
        logger.warning("smart-capture extract classifier call failed: %s", e)
        return {"ok": False, "error": f"Classifier call failed: {e}"}

    intents = _parse_intents(result.content or "", text, asset)

    # Bind the (single) resolved asset into every intent's hash, then mint.
    intent_objs = [CaptureIntent.from_dict(i, asset_id=asset_id) for i in intents]
    secret = await get_token_secret(conn)
    token = mint([io.hash() for io in intent_objs], user_id, workspace_id, secret, now)

    return {
        "ok": True,
        "intents": [io.to_dict() for io in intent_objs],
        "asset": asset if asset_id else None,
        "raw_text": text or None,
        "extract_token": token,
    }
