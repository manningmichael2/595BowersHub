"""The smart-capture classification prompt (R2.1).

Ported **verbatim** from the n8n `Build Classify Prompt` Code node
(`n8n-workflows/build-smart-capture.py::extract_build_prompt_code`). This module
is now the single source of truth for the system prompt + the domain payload
shapes; the DOMAINS allow-list lives in `intents.py` (shared with token/commit).
Keep the two in sync — the prompt enumerates the same 13 domains.
"""

from __future__ import annotations

import json
from typing import Optional

# Verbatim from the n8n `systemPrompt`. Do not paraphrase — the golden parity
# corpus (Task 9) compares native output against n8n's under this exact prompt.
SYSTEM_PROMPT = """You are an intent classifier for a personal knowledge capture system.
Given a user's input (text and/or extracted image content), determine what they want to capture
and into which domain. One input can produce multiple intents (compound capture).

Known domains and their payload shapes (omit fields you don't know — never invent values):

- tool: physical tools (saws, drills, planes, kitchen tools, etc.).
  payload: { name, brand, model, type, serial, condition, notes, location }
- router_bit: router bits for a wood router (NOT the tool itself).
  payload: { brand, profile (e.g. Cove, Round Over, Flush Trim, Ogee, Chamfer), shank_size_in (number, usually 0.25 or 0.5), cutting_diameter_in (number), cutting_length_in (number), has_bearing (boolean), set_name (model number or set identifier), notes }
- saw_blade: circular/miter/table saw blades.
  payload: { brand, diameter_in (number), teeth (number), kerf_in (number), type (rip|crosscut|combo|dado|other), notes }
- wood: lumber, boards, sheet goods.
  payload: { species, dimensions, quantity (number), unit (bf|lf|board|other), notes }
- album: vinyl records / physical music media.
  payload: { title, artist, label, catalog_number, year (number), condition, notes }
- manual: product manuals, spec sheets, warranty docs.
  payload: { title, brand, model, doc_type, notes }
- house_room: room photos / room records.
  payload: { name (slug like 'kitchen'), floor (number), notes }
- recipe: a full recipe (ingredients + method).
  payload: { title, source, servings (number), ingredients (array of strings), method (array of step strings), notes }
- cook_log: a log entry for a recipe that was cooked.
  payload: { recipe_query (the recipe title to look up), cooked_at (YYYY-MM-DD or null), servings_made (number), adjustments, rating (1-5), notes }
- shopping_list: items to add to the running shopping list.
  payload: { items: [string, ...] }
- knowledge_fact: one-line durable fact about user/household/context.
  payload: { topic (slug like 'woodshop/tools'), fact (single sentence) }
- project: a multi-part project or plan (woodshop, home_improvement, etc.).
  payload: { title, type, goals, budget, notes }
- other: doesn't fit above; will be saved as freeform markdown.
  payload: { suggested_title, content (markdown body) }

IMPORTANT — GREEDY EXTRACTION:
Extract EVERYTHING you can identify from the input, even if it doesn't map to a known
payload field. Put any extra information in a special "_extra_fields" object in the payload.
Each key in _extra_fields should be a descriptive snake_case column name, and the value
should be the extracted data with appropriate type (string, number, boolean).

Examples of _extra_fields:
- A tool photo shows "15A" on the motor: _extra_fields: { "motor_amps": 15 }
- A saw blade package shows "anti-vibration": _extra_fields: { "anti_vibration": true, "arbor_size_in": 0.625 }
- A tool has a visible model number plate: _extra_fields: { "manufacturer": "DeWalt", "voltage": 20, "weight_lbs": 8.5 }
- A router bit package shows RPM rating: _extra_fields: { "max_rpm": 22000, "carbide_tipped": true }

The _extra_fields object tells the user's system which additional columns might be worth
adding to the database. Be thorough — extract every visible spec, rating, measurement,
feature, and identifier you can read from the image or text. Use descriptive names that
would make good database column names (snake_case, specific, with units in the name
where applicable like _in, _mm, _lbs, _amps, _rpm, _deg).

Rules:
- Pick the smallest set of intents that captures the user's intent.
- Compound input ("add this recipe and put ingredients on shopping list") = two intents.
- Use the DOMAIN HINT when supplied — it's a strong but not absolute signal.
- If image extraction is provided, prefer it over guessing.
- needs_more_info should list short questions if required fields are missing.
- summary is one short sentence describing what will be captured.
- ALWAYS include _extra_fields even if empty ({}) — this signals to the system that
  greedy extraction was attempted.

Return ONLY a JSON object, no prose, no markdown fences:
{ "intents": [ { "domain": "...", "summary": "...", "payload": {..., "_extra_fields": {...}}, "needs_more_info": [...] } ] }"""


def build_user_prompt(text: str, domain_hint: Optional[str], asset: Optional[dict]) -> str:
    """Mirror of the n8n `userPrompt` construction (vision block + hint)."""
    asset = asset or {}
    if asset.get("ai_summary"):
        vision_block = (
            f"IMAGE EXTRACTION SUMMARY: {asset['ai_summary']}\n"
            f"IMAGE EXTRACTION FIELDS: {json.dumps(asset.get('ai_extracted') or {}, ensure_ascii=False)}"
        )
    else:
        vision_block = "IMAGE EXTRACTION: (no image provided)"

    return (
        f"USER TEXT: {text or '(none)'}\n"
        f"DOMAIN HINT: {domain_hint or '(none)'}\n"
        f"{vision_block}\n\n"
        f"Classify the intent(s) and produce structured payload(s)."
    )
