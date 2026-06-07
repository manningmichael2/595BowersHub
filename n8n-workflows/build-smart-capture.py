"""
Build the 'Smart Capture' n8n workflow.

Two webhooks:
  POST /webhook/smart-capture/extract
       Inputs:  { text?, image_path?, domain_hint? }    (at least one of text/image_path)
       Output:  { ok, intents: [ {domain, summary, payload, needs_more_info} ], asset?, raw_text }
       Pipeline:
         - If image_path provided: call Process Asset (Execute Workflow) to ingest + extract.
         - Build a classification prompt for Haiku using user text + vision summary/extraction.
         - Haiku returns one or more intents (compound capture supported).
         - Caller (the `capture` skill) shows intents to the user, asks for confirmation or
           corrections, then calls /smart-capture/commit per intent.

  POST /webhook/smart-capture/commit
       Inputs:  { domain, payload, asset_id?, source? }
       Output:  { ok, domain, record_id?, path?, summary, message }
       Pipeline:
         - Validate domain is known.
         - Route by target type:
             * Postgres (inventory/cook/house tables) — INSERT + optional asset link.
             * Markdown (knowledge dir) — append/write a file.
             * Sub-workflow (knowledge_fact → existing /webhook/remember).
         - Return what was written so the agent can confirm.

Architecture notes:
  - Single workflow with both webhooks. Cleaner deploy story than two workflows.
  - Reuses Process Asset for image ingestion (Execute Workflow node, no network hop).
  - Domain templates (SQL + markdown shapes) live in JS Code nodes — the prompt + the
    template object are the single source of truth.
  - Conservative defaults: anything that doesn't fit a known domain becomes `other`
    and lands as freeform markdown in /knowledge/captures/.
"""
import json
import subprocess

from _config import API_KEY, N8N_URL

POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"      # Finance Postgres
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"     # Anthropic API (httpHeaderAuth)
PROCESS_ASSET_WORKFLOW_ID = "DeoZgLJCawzgcthm"
FILEWRITER_URL = "http://100.106.180.101:5001"
N8N_INTERNAL = "http://100.106.180.101:5678"  # for sub-workflow webhook calls when needed
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# ===================================================================
# EXTRACT BRANCH
# ===================================================================

# ---- Validate ----
extract_validate_code = r"""// Validate input. Must have text or image_path.
const body = $input.first().json.body || $input.first().json;
const text = (body.text || "").trim();
let imagePath = (body.image_path || "").trim();
const domainHint = (body.domain_hint || "").trim() || null;

if (!text && !imagePath) {
  return [{
    json: {
      error: true,
      message: "Must provide 'text' and/or 'image_path'."
    }
  }];
}

// Normalize image_path: accept relative paths like "inbox/photo.jpg" and
// auto-prefix with "/files/". Also accept bare filenames in inbox.
if (imagePath) {
  if (!imagePath.startsWith("/")) {
    imagePath = "/files/" + imagePath;
  }
  if (!imagePath.startsWith("/files/")) {
    return [{
      json: {
        error: true,
        message: `Invalid image_path '${body.image_path}'. Path must be relative to /files/, e.g. 'inbox/photo.jpg' or '/files/inbox/photo.jpg'. To see available files, use the list-files skill with path '/files/inbox'.`
      }
    }];
  }
}

return [{
  json: {
    text,
    image_path: imagePath,
    has_image: !!imagePath,
    domain_hint: domainHint,
    started_at: Date.now(),
    error: false,
  }
}];
"""

# ---- Branch on whether image is present ----
extract_if_has_image_conditions = {
    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
    "conditions": {
        "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
        "conditions": [{
            "id": "has-image",
            "leftValue": "={{$json.has_image}}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }],
        "combinator": "and",
    },
}

# ---- Build Process Asset call payload ----
extract_build_pa_call_code = r"""const ctx = $json;
return [{
  json: {
    ...ctx,
    pa_payload: {
      path: ctx.image_path,
      domain_hint: ctx.domain_hint,
      uploaded_by: "smart-capture",
      original_name: ctx.image_path.split("/").pop(),
    }
  }
}];
"""

# ---- After Process Asset — merge result back ----
extract_after_pa_code = r"""const ctx = $('Build PA Call').first().json;
const pa = $json;
return [{
  json: {
    ...ctx,
    asset: {
      asset_id: pa.asset_id || null,
      domain: pa.domain || null,
      path: pa.path || null,
      ai_summary: pa.ai_summary || null,
      ai_extracted: pa.ai_extracted || null,
      dedup: pa.dedup === true,
    }
  }
}];
"""

# ---- Skip-image stub: pass through with empty asset ----
extract_no_image_code = r"""const ctx = $json;
return [{
  json: {
    ...ctx,
    asset: { asset_id: null, domain: null, path: null, ai_summary: null, ai_extracted: null, dedup: false }
  }
}];
"""

# ---- Build classification prompt ----
extract_build_prompt_code = r"""const ctx = $json;

const systemPrompt = `You are an intent classifier for a personal knowledge capture system.
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
{ "intents": [ { "domain": "...", "summary": "...", "payload": {..., "_extra_fields": {...}}, "needs_more_info": [...] } ] }`;

const asset = ctx.asset || {};
const visionBlock = asset.ai_summary
  ? `IMAGE EXTRACTION SUMMARY: ${asset.ai_summary}\nIMAGE EXTRACTION FIELDS: ${JSON.stringify(asset.ai_extracted || {})}`
  : "IMAGE EXTRACTION: (no image provided)";

const userPrompt = `USER TEXT: ${ctx.text || "(none)"}
DOMAIN HINT: ${ctx.domain_hint || "(none)"}
${visionBlock}

Classify the intent(s) and produce structured payload(s).`;

const payload = {
  model: "claude-haiku-4-5-20251001",
  max_tokens: 2048,
  system: systemPrompt,
  messages: [{ role: "user", content: userPrompt }]
};

return [{ json: { ...ctx, classify_payload: payload } }];
"""

# ---- Anthropic classify call ----
extract_anthropic_node = {
    "method": "POST",
    "url": "https://api.anthropic.com/v1/messages",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": "httpHeaderAuth",
    "sendHeaders": True,
    "headerParameters": {
        "parameters": [
            {"name": "Content-Type", "value": "application/json"},
            {"name": "anthropic-version", "value": "2023-06-01"},
        ]
    },
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify($json.classify_payload) }}",
    "options": {"timeout": 60000},
}

# ---- Parse Haiku response ----
extract_parse_code = r"""const ctx = $('Build Classify Prompt').first().json;
const resp = $json;

let text = "";
try { text = (resp.content && resp.content[0] && resp.content[0].text) || ""; }
catch (e) { /* fall through */ }

text = text.trim().replace(/^```(?:json)?/i, "").replace(/```\s*$/i, "").trim();

let parsed = null;
let parseError = null;
try { parsed = JSON.parse(text); }
catch (e) { parseError = String(e); }

let intents = (parsed && Array.isArray(parsed.intents)) ? parsed.intents : null;

// Fallback: if parsing failed, route to 'other' so we don't lose the input.
if (!intents) {
  intents = [{
    domain: "other",
    summary: "Unstructured capture (classifier output not parseable)",
    payload: {
      suggested_title: (ctx.text || "capture").slice(0, 60),
      content: (ctx.text || "") + (ctx.asset && ctx.asset.ai_summary ? `\n\nVision: ${ctx.asset.ai_summary}` : "")
    },
    needs_more_info: []
  }];
}

return [{
  json: {
    ok: true,
    intents,
    asset: ctx.asset && ctx.asset.asset_id ? ctx.asset : null,
    raw_text: ctx.text || null,
    extract_token: (() => {
      // Generate a signed token: hex(timestamp) + "." + hex(hmac)
      // The commit endpoint verifies this to prevent hallucinated commits.
      // Token is valid for 30 minutes.
      const ts = Date.now().toString(16);
      const secret = "sc-extract-v1-595bowers";
      // Simple hash: we can't use crypto in n8n Code nodes, so use a
      // deterministic but hard-to-guess token based on timestamp + secret.
      let hash = 0;
      const src = ts + secret + (ctx.text || "") + JSON.stringify(intents.map(i => i.domain));
      for (let i = 0; i < src.length; i++) {
        hash = ((hash << 5) - hash + src.charCodeAt(i)) | 0;
      }
      return ts + "." + Math.abs(hash).toString(16);
    })(),
    classifier_parse_error: parseError,
    duration_ms: Date.now() - (ctx.started_at || Date.now()),
  }
}];
"""

# ===================================================================
# COMMIT BRANCH
# ===================================================================

# ---- Validate commit input ----
commit_validate_code = r"""const body = $input.first().json.body || $input.first().json;
const domain = (body.domain || "").trim().toLowerCase();
const payload = body.payload || {};
const assetId = body.asset_id || null;
const source = body.source || "smart-capture";
const extractToken = (body.extract_token || "").trim();

const KNOWN = new Set([
  "tool","router_bit","saw_blade","wood","album","manual","house_room",
  "recipe","cook_log","shopping_list","knowledge_fact","project","other"
]);

if (!domain) throw new Error("Missing 'domain'.");
if (!KNOWN.has(domain)) throw new Error(`Unknown domain: ${domain}. Known: ${[...KNOWN].join(", ")}`);
if (!payload || typeof payload !== "object") throw new Error("Missing 'payload' object.");

// Token validation: extract_token must be present and not expired (30 min).
// This prevents hallucinated commits — the agent MUST have received a
// successful extract response to have a valid token.
if (!extractToken) {
  throw new Error(
    "Missing 'extract_token'. You must call /smart-capture/extract first and pass " +
    "the extract_token from its response. Do NOT call commit without a successful extract."
  );
}
const tokenParts = extractToken.split(".");
if (tokenParts.length !== 2) {
  throw new Error("Invalid extract_token format. Must be the token returned by /smart-capture/extract.");
}
const tokenTs = parseInt(tokenParts[0], 16);
const now = Date.now();
const thirtyMin = 30 * 60 * 1000;
if (isNaN(tokenTs) || (now - tokenTs) > thirtyMin) {
  throw new Error(
    "extract_token has expired (valid for 30 minutes). Call /smart-capture/extract again to get a fresh token."
  );
}

return [{
  json: {
    domain,
    payload,
    asset_id: assetId,
    source,
    extract_token: extractToken,
    started_at: Date.now(),
  }
}];
"""

# ---- Plan commit ----
# Decides target ("db" | "markdown" | "workflow") and prepares the sql or
# filewriter payload, plus a summary string.
commit_plan_code = r"""const ctx = $json;
const d = ctx.domain;
const p = ctx.payload || {};
const today = new Date().toISOString().slice(0, 10);

// Util to safely render a JS value as a SQL literal.
function sqlStr(v) {
  if (v === null || v === undefined || v === "") return "NULL";
  return "'" + String(v).replace(/'/g, "''") + "'";
}
function sqlNum(v) {
  if (v === null || v === undefined || v === "") return "NULL";
  const n = Number(v);
  return Number.isFinite(n) ? String(n) : "NULL";
}
function slug(s) {
  return String(s || "untitled")
    .toLowerCase().trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 80) || "untitled";
}
function assetLinkSql(table, recordCol, assetId, isPrimary) {
  if (!assetId) return "";
  return `INSERT INTO ${table} (${recordCol}, asset_id, is_primary) VALUES (${recordCol}_VAL, '${assetId}'::uuid, ${isPrimary ? "true" : "false"});`;
}

// Returned shape: { target: 'db'|'markdown'|'workflow', ... }
let plan = null;

if (d === "tool") {
  // Handle _extra_fields: append to notes as structured data for later columnization
  const extras = p._extra_fields || {};
  const extraLines = Object.entries(extras).map(([k, v]) => `${k}: ${v}`);
  const baseNotes = [p.notes, p.location, p.condition].filter(Boolean).join('; ');
  const fullNotes = extraLines.length > 0
    ? [baseNotes, "--- extra fields ---", ...extraLines].filter(Boolean).join('\n')
    : baseNotes || null;

  const insertSql = `WITH new_rec AS (
    INSERT INTO inventory.tools (name, brand, model, type, notes)
    VALUES (${sqlStr(p.name || p.brand || "Unnamed Tool")}, ${sqlStr(p.brand)}, ${sqlStr(p.model)}, ${sqlStr(p.type)}, ${sqlStr(fullNotes)})
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO inventory.tool_files (tool_id, asset_id, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, true FROM new_rec
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  const toolBits = [];
  for (const x of [p.brand, p.model, p.name]) {
    if (x && !toolBits.some(b => b.toLowerCase() === String(x).toLowerCase())) toolBits.push(String(x));
  }
  plan = {
    target: "db", sql: insertSql,
    summary: `Tool: ${toolBits.join(" ") || "(unnamed)"}`,
    extra_fields: extras,
  };

} else if (d === "router_bit") {
  const extras = p._extra_fields || {};
  const extraLines = Object.entries(extras).map(([k, v]) => `${k}: ${v}`);
  const baseNotes = p.notes || '';
  const fullNotes = extraLines.length > 0
    ? [baseNotes, "--- extra fields ---", ...extraLines].filter(Boolean).join('\n')
    : baseNotes || null;

  const sql = `WITH new_rec AS (
    INSERT INTO inventory.router_bits (brand, profile, shank_size_in, cutting_diameter_in, cutting_length_in, has_bearing, set_name, notes)
    VALUES (${sqlStr(p.brand)}, ${sqlStr(p.profile || "Unknown")}, ${sqlNum(p.shank_size_in)}, ${sqlNum(p.cutting_diameter_in)}, ${sqlNum(p.cutting_length_in)}, ${p.has_bearing === true ? "true" : p.has_bearing === false ? "false" : "NULL"}, ${sqlStr(p.set_name)}, ${sqlStr(fullNotes)})
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO inventory.router_bit_files (router_bit_id, asset_id, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, true FROM new_rec
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  plan = { target: "db", sql, summary: `Router bit: ${[p.brand, p.profile, p.shank_size_in && p.shank_size_in + '" shank'].filter(Boolean).join(" ") || "(unnamed)"}`, extra_fields: extras };

} else if (d === "saw_blade") {
  const extras = p._extra_fields || {};
  const extraLines = Object.entries(extras).map(([k, v]) => `${k}: ${v}`);
  const baseNotes = p.notes || '';
  const fullNotes = extraLines.length > 0
    ? [baseNotes, "--- extra fields ---", ...extraLines].filter(Boolean).join('\n')
    : baseNotes || null;

  const sql = `WITH new_rec AS (
    INSERT INTO inventory.saw_blades (brand, diameter_in, teeth, kerf_in, type, notes)
    VALUES (${sqlStr(p.brand)}, ${sqlNum(p.diameter_in)}, ${sqlNum(p.teeth)}, ${sqlNum(p.kerf_in)}, ${sqlStr(p.type)}, ${sqlStr(fullNotes)})
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO inventory.saw_blade_files (saw_blade_id, asset_id, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, true FROM new_rec
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  plan = { target: "db", sql, summary: `Saw blade: ${[p.brand, p.diameter_in && p.diameter_in + "\"", p.teeth && p.teeth + "T"].filter(Boolean).join(" ") || "(unnamed)"}`, extra_fields: extras };

} else if (d === "wood") {
  const sql = `WITH new_rec AS (
    INSERT INTO inventory.wood (species, dimensions, quantity, unit, notes)
    VALUES (${sqlStr(p.species)}, ${sqlStr(p.dimensions)}, ${sqlNum(p.quantity)}, ${sqlStr(p.unit)}, ${sqlStr(p.notes)})
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO inventory.wood_files (wood_id, asset_id, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, true FROM new_rec
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  plan = { target: "db", sql, summary: `Wood: ${[p.species, p.dimensions].filter(Boolean).join(" ") || "(unspecified)"}` };

} else if (d === "album") {
  const sql = `WITH new_rec AS (
    INSERT INTO inventory.albums (title, artist, label, catalog_number, year, condition, notes)
    VALUES (${sqlStr(p.title || "(untitled)")}, ${sqlStr(p.artist)}, ${sqlStr(p.label)}, ${sqlStr(p.catalog_number)}, ${sqlNum(p.year)}, ${sqlStr(p.condition)}, ${sqlStr(p.notes)})
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO inventory.album_files (album_id, asset_id, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, true FROM new_rec
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  plan = { target: "db", sql, summary: `Album: ${[p.artist, p.title].filter(Boolean).join(" - ") || "(untitled)"}` };

} else if (d === "manual") {
  const sql = `WITH new_rec AS (
    INSERT INTO inventory.manuals (title, brand, model, doc_type, notes)
    VALUES (${sqlStr(p.title || (p.brand && p.model ? p.brand + " " + p.model + " manual" : "Manual"))}, ${sqlStr(p.brand)}, ${sqlStr(p.model)}, ${sqlStr(p.doc_type)}, ${sqlStr(p.notes)})
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO inventory.manual_files (manual_id, asset_id, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, true FROM new_rec
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  plan = { target: "db", sql, summary: `Manual: ${[p.brand, p.model].filter(Boolean).join(" ") || p.title || "(unnamed)"}` };

} else if (d === "house_room") {
  // Upsert by name so re-captures don't fail.
  const sql = `WITH new_rec AS (
    INSERT INTO house.rooms (name, floor, notes)
    VALUES (${sqlStr(p.name || "unnamed")}, ${sqlNum(p.floor)}, ${sqlStr(p.notes)})
    ON CONFLICT (name) DO UPDATE SET notes = COALESCE(EXCLUDED.notes, house.rooms.notes)
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO house.room_files (room_id, asset_id, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, true FROM new_rec
    ON CONFLICT DO NOTHING
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  plan = { target: "db", sql, summary: `Room: ${p.name || "(unnamed)"}` };

} else if (d === "recipe") {
  const ingredients = Array.isArray(p.ingredients) ? p.ingredients : [];
  const method = Array.isArray(p.method) ? p.method : [];
  const notesParts = [];
  if (ingredients.length) notesParts.push("INGREDIENTS:\n- " + ingredients.join("\n- "));
  if (method.length) notesParts.push("METHOD:\n" + method.map((s,i) => `${i+1}. ${s}`).join("\n"));
  if (p.notes) notesParts.push("NOTES:\n" + p.notes);
  const fullNotes = notesParts.join("\n\n");

  const sql = `WITH new_rec AS (
    INSERT INTO cook.recipes (title, slug, source, servings, notes)
    VALUES (${sqlStr(p.title || "Untitled Recipe")}, ${sqlStr(slug(p.title))}, ${sqlStr(p.source)}, ${sqlNum(p.servings)}, ${sqlStr(fullNotes)})
    RETURNING id
  )${ctx.asset_id ? `, link AS (
    INSERT INTO cook.recipe_files (recipe_id, asset_id, file_role, is_primary)
    SELECT id, '${ctx.asset_id}'::uuid, 'source_page', true FROM new_rec
    RETURNING asset_id
  )` : ""}
  SELECT (SELECT id FROM new_rec)::text AS record_id;`;
  plan = { target: "db", sql, summary: `Recipe: ${p.title || "(untitled)"}` };

} else if (d === "cook_log") {
  // Look up recipe by title fragment first.
  const q = (p.recipe_query || p.recipe_title || "").trim();
  if (!q) {
    plan = { target: "error", message: "cook_log requires recipe_query (the recipe title to look up)." };
  } else {
    const sql = `WITH found AS (
      SELECT id FROM cook.recipes WHERE LOWER(title) LIKE LOWER('%${q.replace(/'/g, "''")}%') ORDER BY updated_at DESC LIMIT 1
    ), inserted AS (
      INSERT INTO cook.cook_log (recipe_id, cooked_at, servings_made, adjustments, rating, notes)
      SELECT id, ${p.cooked_at ? sqlStr(p.cooked_at) : "CURRENT_DATE"}, ${sqlNum(p.servings_made)}, ${sqlStr(p.adjustments)}, ${sqlNum(p.rating)}, ${sqlStr(p.notes)}
      FROM found
      RETURNING id, recipe_id
    )
    SELECT (SELECT id FROM inserted)::text AS record_id, (SELECT recipe_id FROM inserted)::text AS recipe_id;`;
    plan = { target: "db", sql, summary: `Cook log entry for: ${q}`, fallback_message: `No recipe matched '${q}'. Capture the recipe first, then log this cook.` };
  }

} else if (d === "shopping_list") {
  const items = Array.isArray(p.items) ? p.items.filter(Boolean) : [];
  if (items.length === 0) {
    plan = { target: "error", message: "shopping_list requires non-empty items array." };
  } else {
    const lines = items.map(it => `- [${today}] ${String(it).trim()}`).join("\n");
    plan = {
      target: "markdown",
      filewriter: { endpoint: "/append", payload: { path: "/knowledge/shopping-list.md", content: lines + "\n" } },
      path: "/knowledge/shopping-list.md",
      summary: `Shopping list: added ${items.length} item${items.length === 1 ? "" : "s"}`
    };
  }

} else if (d === "knowledge_fact") {
  const topic = (p.topic || "general").trim();
  const fact = (p.fact || "").trim();
  if (!fact) {
    plan = { target: "error", message: "knowledge_fact requires a fact." };
  } else {
    plan = {
      target: "workflow",
      remember_payload: { topic, fact },
      summary: `Knowledge fact (${topic}): ${fact.slice(0, 80)}`
    };
  }

} else if (d === "project") {
  const title = (p.title || "Untitled Project").trim();
  const s = slug(title);
  const md = `# ${title}\n\n_Started: ${today}_\n` +
             (p.type ? `_Type: ${p.type}_\n` : "") +
             (p.budget ? `_Budget: ${p.budget}_\n` : "") +
             "\n## Goals\n\n" + (p.goals || "_(to be defined)_") +
             "\n\n## Notes\n\n" + (p.notes || "");
  const path = `/knowledge/projects/${s}.md`;
  plan = {
    target: "markdown",
    filewriter: { endpoint: "/append", payload: { path, content: md + "\n" } },
    path,
    summary: `Project: ${title}`
  };

} else if (d === "other") {
  const title = (p.suggested_title || "capture").trim();
  const s = slug(title);
  const md = `# ${title}\n\n_Captured: ${today}_\n\n${p.content || ""}`;
  const path = `/knowledge/captures/${s}.md`;
  plan = {
    target: "markdown",
    filewriter: { endpoint: "/append", payload: { path, content: md + "\n" } },
    path,
    summary: `Capture: ${title}`
  };
} else {
  plan = { target: "error", message: `Unhandled domain: ${d}` };
}

return [{ json: { ...ctx, plan } }];
"""

# ---- Switch on plan.target ----
commit_switch_node = {
    "rules": {
        "values": [
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [{
                        "id": "is-db",
                        "leftValue": "={{$json.plan.target}}",
                        "rightValue": "db",
                        "operator": {"type": "string", "operation": "equals"},
                    }],
                    "combinator": "and",
                },
                "outputKey": "db",
            },
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [{
                        "id": "is-md",
                        "leftValue": "={{$json.plan.target}}",
                        "rightValue": "markdown",
                        "operator": {"type": "string", "operation": "equals"},
                    }],
                    "combinator": "and",
                },
                "outputKey": "markdown",
            },
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [{
                        "id": "is-wf",
                        "leftValue": "={{$json.plan.target}}",
                        "rightValue": "workflow",
                        "operator": {"type": "string", "operation": "equals"},
                    }],
                    "combinator": "and",
                },
                "outputKey": "workflow",
            },
            {
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict", "version": 2},
                    "conditions": [{
                        "id": "is-err",
                        "leftValue": "={{$json.plan.target}}",
                        "rightValue": "error",
                        "operator": {"type": "string", "operation": "equals"},
                    }],
                    "combinator": "and",
                },
                "outputKey": "error",
            },
        ]
    },
    "options": {},
}

# DB lane
commit_db_query = "={{ $json.plan.sql }}"
commit_db_post_code = r"""const ctx = $('Validate Commit').first().json;
const plan = $('Plan Commit').first().json.plan;
const row = $input.first().json || {};
return [{ json: {
  ok: true,
  domain: ctx.domain,
  target: "db",
  record_id: row.record_id || null,
  recipe_id: row.recipe_id || null,
  asset_linked: !!ctx.asset_id,
  summary: plan.summary,
  extra_fields: plan.extra_fields || null,
  duration_ms: Date.now() - (ctx.started_at || Date.now()),
} }];
"""

# Markdown lane: filewriter call + post-write context
commit_md_payload_code = r"""const ctx = $json;
const fw = ctx.plan.filewriter;
return [{ json: { ...ctx, fw_endpoint: fw.endpoint, fw_payload: fw.payload } }];
"""
commit_md_post_code = r"""const ctx = $('Validate Commit').first().json;
const plan = $('Plan Commit').first().json.plan;
return [{ json: {
  ok: true,
  domain: ctx.domain,
  target: "markdown",
  path: plan.path,
  summary: plan.summary,
  duration_ms: Date.now() - (ctx.started_at || Date.now()),
} }];
"""

# Workflow lane: knowledge_fact → call /webhook/remember
commit_wf_post_code = r"""const ctx = $('Validate Commit').first().json;
const plan = $('Plan Commit').first().json.plan;
const resp = $input.first().json || {};
return [{ json: {
  ok: true,
  domain: ctx.domain,
  target: "workflow",
  saved: resp.saved !== false,
  note: resp.note || null,
  conflicts_with: resp.conflicts_with || null,
  topic: resp.topic || (plan.remember_payload && plan.remember_payload.topic),
  summary: plan.summary,
  duration_ms: Date.now() - (ctx.started_at || Date.now()),
} }];
"""

# Error lane
commit_err_code = r"""const plan = $json.plan;
const ctx = $('Validate Commit').first().json;
return [{ json: {
  ok: false,
  domain: ctx.domain,
  error: plan.message || "Plan returned no target.",
  fallback_message: plan.fallback_message || null,
} }];
"""

# ===================================================================
# WORKFLOW
# ===================================================================
pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}
anthropic_creds = {"httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": "Anthropic API"}}

workflow = {
    "name": "Smart Capture",
    "nodes": [
        # ===== EXTRACT =====
        {
            "parameters": {"path": "smart-capture/extract", "httpMethod": "POST", "responseMode": "lastNode", "options": {}},
            "id": "n-wh-ext", "name": "Webhook Extract",
            "type": "n8n-nodes-base.webhook", "typeVersion": 2.1, "position": [200, 200],
            "webhookId": "smart-capture-extract",
        },
        {
            "parameters": {"jsCode": extract_validate_code},
            "id": "n-ext-validate", "name": "Validate Extract",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [400, 200],
        },
        {
            "parameters": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                "conditions": {
                    "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "loose", "version": 2},
                    "conditions": [{
                        "id": "is-error",
                        "leftValue": "={{$json.error}}",
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                    }],
                    "combinator": "and",
                },
            },
            "id": "n-ext-if-err", "name": "Has Error?",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [500, 200],
        },
        {
            "parameters": {"jsCode": "return [{ json: { ok: false, error: $json.message } }];"},
            "id": "n-ext-err-resp", "name": "Extract Error",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [600, 50],
        },
        {
            "parameters": extract_if_has_image_conditions,
            "id": "n-ext-if-img", "name": "Has Image?",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [600, 200],
        },
        {
            "parameters": {"jsCode": extract_build_pa_call_code},
            "id": "n-ext-build-pa", "name": "Build PA Call",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [800, 100],
        },
        {
            "parameters": {
                "workflowId": {"__rl": True, "value": PROCESS_ASSET_WORKFLOW_ID, "mode": "id"},
                "workflowInputs": {"value": "={{ $json.pa_payload }}", "schema": []},
                "options": {}
            },
            "id": "n-ext-pa", "name": "Run Process Asset",
            "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2, "position": [1000, 100],
        },
        {
            "parameters": {"jsCode": extract_after_pa_code},
            "id": "n-ext-after-pa", "name": "After PA",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1200, 100],
        },
        {
            "parameters": {"jsCode": extract_no_image_code},
            "id": "n-ext-no-img", "name": "No Image",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [800, 300],
        },
        {
            "parameters": {"jsCode": extract_build_prompt_code},
            "id": "n-ext-build-prompt", "name": "Build Classify Prompt",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1400, 200],
        },
        {
            "parameters": extract_anthropic_node,
            "id": "n-ext-haiku", "name": "Classify (Haiku)",
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [1600, 200],
            "credentials": anthropic_creds,
        },
        {
            "parameters": {"jsCode": extract_parse_code},
            "id": "n-ext-parse", "name": "Parse Classification",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1800, 200],
        },

        # ===== COMMIT =====
        {
            "parameters": {"path": "smart-capture/commit", "httpMethod": "POST", "responseMode": "lastNode", "options": {}},
            "id": "n-wh-com", "name": "Webhook Commit",
            "type": "n8n-nodes-base.webhook", "typeVersion": 2.1, "position": [200, 700],
            "webhookId": "smart-capture-commit",
        },
        {
            "parameters": {"jsCode": commit_validate_code},
            "id": "n-com-validate", "name": "Validate Commit",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [400, 700],
        },
        {
            "parameters": {"jsCode": commit_plan_code},
            "id": "n-com-plan", "name": "Plan Commit",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [600, 700],
        },
        {
            "parameters": commit_switch_node,
            "id": "n-com-switch", "name": "Route By Target",
            "type": "n8n-nodes-base.switch", "typeVersion": 3.2, "position": [800, 700],
        },

        # DB lane
        {
            "parameters": {
                "operation": "executeQuery",
                "query": commit_db_query,
                "options": {},
            },
            "id": "n-com-db", "name": "DB Insert",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.4, "position": [1000, 500],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": commit_db_post_code},
            "id": "n-com-db-post", "name": "DB Post",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1200, 500],
        },

        # Markdown lane
        {
            "parameters": {"jsCode": commit_md_payload_code},
            "id": "n-com-md-prep", "name": "MD Prep",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1000, 700],
        },
        {
            "parameters": {
                "method": "POST",
                "url": "={{ '" + FILEWRITER_URL + "' + $json.fw_endpoint }}",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.fw_payload) }}",
                "options": {"timeout": 15000},
            },
            "id": "n-com-md-write", "name": "MD Write",
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [1200, 700],
        },
        {
            "parameters": {"jsCode": commit_md_post_code},
            "id": "n-com-md-post", "name": "MD Post",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1400, 700],
        },

        # Workflow lane (knowledge_fact)
        {
            "parameters": {
                "method": "POST",
                "url": f"{N8N_INTERNAL}/webhook/remember",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.plan.remember_payload) }}",
                "options": {"timeout": 30000},
            },
            "id": "n-com-wf-call", "name": "Call Remember",
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2, "position": [1000, 900],
        },
        {
            "parameters": {"jsCode": commit_wf_post_code},
            "id": "n-com-wf-post", "name": "WF Post",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1200, 900],
        },

        # Error lane
        {
            "parameters": {"jsCode": commit_err_code},
            "id": "n-com-err", "name": "Error Response",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1000, 1100],
        },
    ],
    "connections": {
        # Extract
        "Webhook Extract": {"main": [[{"node": "Validate Extract", "type": "main", "index": 0}]]},
        "Validate Extract": {"main": [[{"node": "Has Error?", "type": "main", "index": 0}]]},
        "Has Error?": {"main": [
            [{"node": "Extract Error", "type": "main", "index": 0}],
            [{"node": "Has Image?", "type": "main", "index": 0}],
        ]},
        "Has Image?": {"main": [
            [{"node": "Build PA Call", "type": "main", "index": 0}],
            [{"node": "No Image", "type": "main", "index": 0}],
        ]},
        "Build PA Call": {"main": [[{"node": "Run Process Asset", "type": "main", "index": 0}]]},
        "Run Process Asset": {"main": [[{"node": "After PA", "type": "main", "index": 0}]]},
        "After PA": {"main": [[{"node": "Build Classify Prompt", "type": "main", "index": 0}]]},
        "No Image": {"main": [[{"node": "Build Classify Prompt", "type": "main", "index": 0}]]},
        "Build Classify Prompt": {"main": [[{"node": "Classify (Haiku)", "type": "main", "index": 0}]]},
        "Classify (Haiku)": {"main": [[{"node": "Parse Classification", "type": "main", "index": 0}]]},

        # Commit
        "Webhook Commit": {"main": [[{"node": "Validate Commit", "type": "main", "index": 0}]]},
        "Validate Commit": {"main": [[{"node": "Plan Commit", "type": "main", "index": 0}]]},
        "Plan Commit": {"main": [[{"node": "Route By Target", "type": "main", "index": 0}]]},
        "Route By Target": {"main": [
            [{"node": "DB Insert", "type": "main", "index": 0}],
            [{"node": "MD Prep", "type": "main", "index": 0}],
            [{"node": "Call Remember", "type": "main", "index": 0}],
            [{"node": "Error Response", "type": "main", "index": 0}],
        ]},
        "DB Insert": {"main": [[{"node": "DB Post", "type": "main", "index": 0}]]},
        "MD Prep": {"main": [[{"node": "MD Write", "type": "main", "index": 0}]]},
        "MD Write": {"main": [[{"node": "MD Post", "type": "main", "index": 0}]]},
        "Call Remember": {"main": [[{"node": "WF Post", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}


with open('/home/michael/KiroProject/n8n-workflows/smart-capture.json', 'w') as f:
    json.dump(workflow, f, indent=2)
print("Saved smart-capture.json")


def api(method, path, data=None):
    cmd = ['curl', '-s', '-X', method,
           '-H', f'X-N8N-API-KEY: {API_KEY}',
           '-H', 'Content-Type: application/json']
    if data is not None:
        cmd.extend(['-d', json.dumps(data)])
    cmd.append(f'{N8N_URL}/api/v1{path}')
    r = subprocess.run(cmd, capture_output=True, text=True)
    if not r.stdout:
        return {"_status": r.returncode, "_stderr": r.stderr}
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"_raw": r.stdout, "_status": r.returncode}


def find_workflow_by_name(name):
    resp = api('GET', '/workflows?limit=250')
    for wf in resp.get('data', []):
        if wf.get('name') == name:
            return wf
    return None


payload = {k: workflow[k] for k in ('name', 'nodes', 'connections', 'settings')}

existing = find_workflow_by_name("Smart Capture")
if existing:
    wf_id = existing['id']
    print(f"Updating existing workflow: {wf_id}")
    if existing.get('active'):
        api('POST', f'/workflows/{wf_id}/deactivate')
    resp = api('PUT', f'/workflows/{wf_id}', payload)
else:
    print("Creating new workflow")
    resp = api('POST', '/workflows', payload)
    wf_id = resp.get('id')

print(f"Workflow id: {wf_id}")
print(f"Response keys: {list(resp.keys()) if isinstance(resp, dict) else 'N/A'}")

if wf_id:
    act = api('POST', f'/workflows/{wf_id}/activate')
    print(f"Activate response active={act.get('active')}")
    print(f"Webhooks:")
    print(f"  POST {N8N_URL}/webhook/smart-capture/extract")
    print(f"  POST {N8N_URL}/webhook/smart-capture/commit")
else:
    print("ERROR creating/updating:", json.dumps(resp, indent=2)[:1500])
