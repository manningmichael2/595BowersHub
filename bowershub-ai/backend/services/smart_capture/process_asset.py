"""Native Process Asset — vision ingest (R3.1 / R2.4).

Ports the n8n `Process Asset` sub-workflow in-process: probe → sha256 dedup →
insert `files.assets` → Claude vision (`ai_summary` + `ai_extracted`) → move to
the domain's permanent home → update the row. Filesystem ops go through the
Filewriter HTTP service (which stays — it is not n8n).

All SQL is parameterized (`$n`) — this **fixes** the n8n version's
string-interpolated INSERT/UPDATE (an injection risk on OCR'd filenames/values).

Gated by `smart_capture.process_asset_native`; while off, `engine.py` proxies the
whole image extract to n8n (M4). `extract_native` consumes the returned
`{asset_id, ai_summary, ai_extracted}` to build the classify prompt.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

from backend.http_client import get_http_client
from backend.services.model_catalog import resolve_role

logger = logging.getLogger(__name__)

FILEWRITER_URL = os.environ.get("FILEWRITER_URL", "http://filewriter:5001")

# Per-domain vision prompts + fallback (verbatim from the n8n build_prompt_code).
_PROMPTS = {
    "receipt": "You are extracting fields from a purchase receipt. Return ONLY a JSON object with keys: merchant (string|null), total (number|null), currency (string|null), date (YYYY-MM-DD|null), payment_method (string|null), line_items (array of {description, qty, price} or null), notes (string|null).",
    "tool": "You are inventorying a tool. Return ONLY JSON: {brand, model, type, name, serial, condition, notes}. Use null when unknown. type is e.g. 'saw', 'drill', 'chisel'.",
    "saw_blade": "Inventorying a saw blade. Return ONLY JSON: {brand, diameter_in, teeth, kerf_in, type, notes}. type is rip|crosscut|combo|dado|other. Use null if unknown.",
    "wood": "Inventorying lumber. Return ONLY JSON: {species, dimensions, quantity, unit, notes}. unit is bf|lf|board|other.",
    "album": "Inventorying a vinyl record. Return ONLY JSON: {title, artist, label, catalog_number, year, condition, notes}.",
    "manual": "Identifying a product manual or spec sheet. Return ONLY JSON: {title, brand, model, doc_type, notes}.",
    "house_room": "Identifying a room photo. Return ONLY JSON: {room_guess, features, orientation_guess, notes}.",
    "cook_recipe": "Looking at a recipe page or finished dish. Return ONLY JSON: {title, source, ingredients, method_summary, is_finished_dish, notes}.",
}
_FALLBACK_PROMPT = (
    "Look at this image and return ONLY a JSON object: {summary (one sentence), "
    "best_domain_guess (one of: receipt, tool, saw_blade, wood, album, manual, "
    "house_room, cook_recipe, other), key_fields (object with anything notable)}."
)

_MOVE_SUBDIRS = {
    "tool": "inventory/tools",
    "saw_blade": "inventory/saw_blades",
    "wood": "inventory/wood",
    "album": "inventory/albums",
    "manual": "manuals",
    "house_room": "house",
    "cook_recipe": "cook",
}


def _rel_path(image_path: str) -> Optional[str]:
    p = (image_path or "").strip()
    if not p:
        return None
    if p.startswith("/files/"):
        p = p[len("/files/"):]
    elif p.startswith("/"):
        return None  # outside the files root
    if ".." in p:
        return None
    return p.lstrip("/")


async def _fw(path: str, body: dict) -> dict:
    client = get_http_client()
    resp = await client.post(f"{FILEWRITER_URL}{path}", json=body, timeout=30.0)
    resp.raise_for_status()
    return resp.json()


def _parse_vision(raw: str) -> tuple[str, dict]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        extracted = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return (text[:200] or "unknown item"), {"_raw": text}
    parts = []
    for k in ("brand", "name", "model", "title", "type"):
        if extracted.get(k):
            parts.append(str(extracted[k]))
            break
    if extracted.get("brand") and parts and parts[0] != str(extracted["brand"]):
        parts.insert(0, str(extracted["brand"]))
    if parts:
        summary = " ".join(dict.fromkeys(parts))
    elif extracted.get("summary"):
        summary = str(extracted["summary"])
    elif extracted.get("merchant") and extracted.get("total") is not None:
        summary = f"{extracted['merchant']} - {extracted['total']}"
    else:
        summary = next(
            (v for v in extracted.values() if isinstance(v, str) and 0 < len(v) < 100),
            "unknown item",
        )
    return summary, extracted


async def process_asset_native(
    *, image_path: str, domain_hint: Optional[str], model_provider, conn
) -> Optional[dict]:
    """Ingest an image → asset row + vision metadata. Returns the asset dict
    (or None on unrecoverable failure so the caller can fall back)."""
    rel = _rel_path(image_path)
    if rel is None:
        logger.warning("process_asset_native: invalid image_path %r", image_path)
        return None
    full_path = f"/files/{rel}"

    try:
        probe = await _fw("/probe", {"path": full_path})
    except Exception as e:
        logger.warning("process_asset_native probe failed for %s: %s", full_path, e)
        return None
    if not probe.get("ok") or not probe.get("exists"):
        logger.warning("process_asset_native: file not found %s", full_path)
        return None

    sha256 = probe.get("sha256")
    mime = probe.get("mime") or ""
    size_bytes = probe.get("size_bytes")

    # sha256 dedup — return the existing asset unchanged.
    dup = await conn.fetchrow(
        "SELECT id::text AS id, path, domain, ai_summary, ai_extracted "
        "FROM files.assets WHERE sha256 = $1 LIMIT 1",
        sha256,
    )
    if dup:
        return {
            "ok": True, "dedup": True, "asset_id": dup["id"], "domain": dup["domain"],
            "path": dup["path"], "ai_summary": dup["ai_summary"],
            "ai_extracted": dup["ai_extracted"],
        }

    asset_id = await conn.fetchval(
        "INSERT INTO files.assets (path, original_name, mime, size_bytes, sha256, domain, uploaded_by) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id::text",
        full_path, rel.split("/")[-1], mime, size_bytes, sha256, domain_hint, "smart-capture",
    )

    ai_summary: Optional[str] = None
    ai_extracted: dict = {}
    ai_model: Optional[str] = None
    resolved_domain = domain_hint or "unknown"

    if mime.startswith("image/"):
        try:
            b64 = await _fw("/read-base64", {"path": full_path})
            if b64.get("ok") and b64.get("base64"):
                prompt = _PROMPTS.get(domain_hint or "", _FALLBACK_PROMPT)
                model = resolve_role("fast")
                result = await model_provider.complete(
                    model=model,
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64["base64"]}},
                            {"type": "text", "text": prompt + "\n\nReturn the JSON object and nothing else."},
                        ],
                    }],
                )
                ai_summary, ai_extracted = _parse_vision(result.content or "")
                ai_model = model
                if not domain_hint and isinstance(ai_extracted, dict) and ai_extracted.get("best_domain_guess"):
                    resolved_domain = str(ai_extracted["best_domain_guess"])
        except Exception as e:  # vision failure is non-fatal — asset row still exists
            logger.warning("process_asset_native vision failed for %s: %s", asset_id, e)
            ai_extracted = {"reason": f"vision failed: {e}"}

    # Move to the domain's permanent home (best-effort — keep original on failure).
    ext_m = re.search(r"\.[A-Za-z0-9]+$", full_path)
    ext = ext_m.group(0).lower() if ext_m else ""
    from datetime import datetime, timezone

    subdir = _MOVE_SUBDIRS.get(resolved_domain)
    if subdir == "receipts" or resolved_domain == "receipt":
        subdir = f"receipts/{datetime.now(timezone.utc).year}"
    new_full = f"/files/{subdir}/{asset_id}{ext}" if subdir else full_path
    if new_full != full_path:
        try:
            await _fw("/move", {"src": full_path, "dst": new_full})
        except Exception as e:
            logger.warning("process_asset_native move failed (%s → %s): %s", full_path, new_full, e)
            new_full = full_path

    await conn.execute(
        "UPDATE files.assets SET path=$2, domain=$3, ai_summary=$4, ai_extracted=$5::jsonb, "
        "ai_model=$6, processed_at=now() WHERE id=$1::uuid",
        asset_id, new_full, resolved_domain, ai_summary, json.dumps(ai_extracted or {}), ai_model,
    )

    return {
        "ok": True, "dedup": False, "asset_id": asset_id, "domain": resolved_domain,
        "path": new_full, "ai_summary": ai_summary, "ai_extracted": ai_extracted,
    }
