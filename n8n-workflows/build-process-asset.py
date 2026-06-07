"""
Build the 'Process Asset' n8n sub-workflow.

This is the canonical pipeline every domain uses for ingesting a file:
  - dedup by sha256
  - record in files.assets
  - run Claude vision for metadata extraction
  - move file from inbox to its permanent home
  - return the asset_id

Triggered by:
  - HTTP webhook  POST /webhook/process-asset    (skills, scripts, future UI)
  - executeWorkflow from other n8n workflows (e.g., email-receipts)

Inputs (JSON body):
  {
    "path":          "inbox/abc.jpg",       # required, relative to /home/node/files
    "domain_hint":   "receipt",             # optional, biases the vision prompt
    "uploaded_by":   "michael",             # optional
    "original_name": "IMG_1234.jpg"         # optional, preserved in DB
  }

Output:
  {
    "ok": true,
    "asset_id": "...",
    "dedup": false,
    "domain": "receipt",
    "path": "/files/receipts/2026/<uuid>.jpg",
    "ai_summary": "...",
    "ai_extracted": { ... },
    "duration_ms": 1234
  }

Filesystem ops are delegated to the Filewriter HTTP service at
http://filewriter:5001 (Docker-internal). Filewriter sees the same disk
under /files (which is /home/michael/files on the host).

n8n cannot use executeCommand (node not available in this install) and
its Code node can't require('fs'), so HTTP calls to Filewriter are the
right pattern — also matches the existing project convention.
"""
import json
import subprocess

from _config import API_KEY, N8N_URL

POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"      # Finance Postgres
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"     # Anthropic API (httpHeaderAuth)

# Filewriter is reachable as http://filewriter:5001 inside the ai-network
# but n8n is on ai-network and filewriter is on its own. Use the host IP via
# Tailscale instead, or just localhost from the host's network. Easiest is
# the host LAN IP since both containers can reach it.
FILEWRITER_URL = "http://100.106.180.101:5001"

# ============================================================
# Code: Validate input
# ============================================================
validate_code = r"""// Validate the incoming request and normalize fields.
const body = $input.first().json.body || $input.first().json;
const relPath = (body.path || "").trim();
if (!relPath) throw new Error("Missing 'path' (relative to /files)");
if (relPath.includes("..") || relPath.startsWith("/")) {
  throw new Error("Invalid path: must be relative and not contain '..'");
}

const fullPath = `/files/${relPath}`;

return [{
  json: {
    rel_path:       relPath,
    full_path:      fullPath,
    domain_hint:    body.domain_hint || null,
    uploaded_by:    body.uploaded_by || "unknown",
    original_name:  body.original_name || relPath.split("/").pop(),
    started_at:     Date.now(),
  }
}];
"""

# ============================================================
# Code: Parse Probe response
# ============================================================
parse_probe_code = r"""// Filewriter returned probe info. Merge with context.
const ctx = $('Validate').first().json;
const probe = $json;
if (!probe.ok || !probe.exists) {
  throw new Error(`File not found: ${ctx.full_path} (${JSON.stringify(probe)})`);
}
return [{
  json: {
    ...ctx,
    size_bytes: probe.size_bytes,
    sha256:     probe.sha256,
    mime:       probe.mime,
  }
}];
"""

# ============================================================
# Postgres: dedup check
# ============================================================
dedup_query = (
    "SELECT id::text AS id, path, domain, ai_summary, ai_extracted "
    "FROM files.assets WHERE sha256 = '{{$json.sha256}}' LIMIT 1"
)

# ============================================================
# Code: Branch on dedup result
# ============================================================
dedup_branch_code = r"""const ctx = $('Parse Probe').first().json;
// Postgres node returns 0 rows when nothing matched; with alwaysOutputData=true
// it still passes one empty item through. Treat anything without an `id` as "no dup".
const rows = $input.all().map(i => i.json).filter(r => r && r.id);
if (rows.length === 0) {
  return [{ json: { ...ctx, dedup: false } }];
}
return [{
  json: {
    ...ctx,
    dedup: true,
    asset_id:     rows[0].id,
    domain:       rows[0].domain,
    path:         rows[0].path,
    ai_summary:   rows[0].ai_summary,
    ai_extracted: rows[0].ai_extracted,
  }
}];
"""

# ============================================================
# IF: dedup?
# ============================================================
if_dedup_conditions = {
    "options": {
        "caseSensitive": True, "leftValue": "",
        "typeValidation": "loose", "version": 2,
    },
    "conditions": {
        "options": {
            "caseSensitive": True, "leftValue": "",
            "typeValidation": "loose", "version": 2,
        },
        "conditions": [{
            "id": "dedup-true",
            "leftValue": "={{$json.dedup}}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }],
        "combinator": "and",
    },
}

# ============================================================
# Postgres: insert new asset row
# ============================================================
insert_query = (
    "INSERT INTO files.assets (path, original_name, mime, size_bytes, sha256, domain, uploaded_by) "
    "VALUES ('{{$json.full_path}}', "
    "        '{{($json.original_name || '').replace(/'/g, \"''\")}}', "
    "        '{{$json.mime}}', "
    "        {{$json.size_bytes}}, "
    "        '{{$json.sha256}}', "
    "        {{$json.domain_hint ? \"'\" + $json.domain_hint + \"'\" : 'NULL'}}, "
    "        '{{($json.uploaded_by || '').replace(/'/g, \"''\")}}') "
    "RETURNING id::text AS id"
)

post_insert_code = r"""const ctx = $('Parse Probe').first().json;
const inserted = $input.first().json;
return [{ json: { ...ctx, asset_id: inserted.id, dedup: false } }];
"""

# ============================================================
# Code: Build Vision Prompt
# ============================================================
build_prompt_code = r"""// Build the Anthropic Vision request payload.
const ctx     = $('Post Insert').first().json;
const b64resp = $json;
const isImage = (ctx.mime || "").startsWith("image/");

if (!isImage || !b64resp.ok) {
  return [{
    json: {
      ...ctx,
      vision_skipped: true,
      ai_model:       null,
      ai_summary:     null,
      ai_extracted:   { reason: isImage ? "base64 read failed" : "non-image input; vision pipeline TODO" },
      resolved_domain: ctx.domain_hint || "unknown",
    }
  }];
}

const PROMPTS = {
  receipt:      "You are extracting fields from a purchase receipt. Return ONLY a JSON object with keys: merchant (string|null), total (number|null), currency (string|null), date (YYYY-MM-DD|null), payment_method (string|null), line_items (array of {description, qty, price} or null), notes (string|null).",
  tool:         "You are inventorying a tool. Return ONLY JSON: {brand, model, type, name, serial, condition, notes}. Use null when unknown. type is e.g. 'saw', 'drill', 'chisel'.",
  saw_blade:    "Inventorying a saw blade. Return ONLY JSON: {brand, diameter_in, teeth, kerf_in, type, notes}. type is rip|crosscut|combo|dado|other. Use null if unknown.",
  wood:         "Inventorying lumber. Return ONLY JSON: {species, dimensions, quantity, unit, notes}. unit is bf|lf|board|other.",
  album:        "Inventorying a vinyl record. Return ONLY JSON: {title, artist, label, catalog_number, year, condition, notes}.",
  manual:       "Identifying a product manual or spec sheet. Return ONLY JSON: {title, brand, model, doc_type, notes}.",
  house_room:   "Identifying a room photo. Return ONLY JSON: {room_guess, features, orientation_guess, notes}.",
  cook_recipe:  "Looking at a recipe page or finished dish. Return ONLY JSON: {title, source, ingredients, method_summary, is_finished_dish, notes}.",
};
const FALLBACK_PROMPT = "Look at this image and return ONLY a JSON object: {summary (one sentence), best_domain_guess (one of: receipt, tool, saw_blade, wood, album, manual, house_room, cook_recipe, other), key_fields (object with anything notable)}.";

const domain = ctx.domain_hint;
const prompt = PROMPTS[domain] || FALLBACK_PROMPT;

const payload = {
  model: "claude-haiku-4-5-20251001",
  max_tokens: 1024,
  messages: [{
    role: "user",
    content: [
      { type: "image", source: { type: "base64", media_type: ctx.mime, data: b64resp.base64 } },
      { type: "text",  text: prompt + "\n\nReturn the JSON object and nothing else." }
    ]
  }]
};

return [{
  json: {
    ...ctx,
    vision_skipped: false,
    vision_payload: payload,
    domain_for_prompt: domain || "fallback",
  }
}];
"""

# ============================================================
# IF: skip vision?
# ============================================================
if_vision_skip_conditions = {
    "options": {
        "caseSensitive": True, "leftValue": "",
        "typeValidation": "loose", "version": 2,
    },
    "conditions": {
        "options": {
            "caseSensitive": True, "leftValue": "",
            "typeValidation": "loose", "version": 2,
        },
        "conditions": [{
            "id": "skip-true",
            "leftValue": "={{$json.vision_skipped}}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }],
        "combinator": "and",
    },
}

# ============================================================
# HTTP: Anthropic Vision
# ============================================================
http_anthropic_node = {
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
    "jsonBody": "={{ JSON.stringify($json.vision_payload) }}",
    "options": {"timeout": 60000},
}

# ============================================================
# Code: Parse vision result
# ============================================================
parse_vision_code = r"""const ctx = $('Build Vision Prompt').first().json;
const resp = $json;
let text = "";
try { text = (resp.content && resp.content[0] && resp.content[0].text) || ""; }
catch (e) { /* fall through */ }

text = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();

let extracted = null;
let summary   = null;
try {
  extracted = JSON.parse(text);
  // Build a clean human-readable summary by combining the most useful fields.
  const parts = [];
  if (extracted.brand) parts.push(extracted.brand);
  if (extracted.name) parts.push(extracted.name);
  else if (extracted.model) parts.push(extracted.model);
  else if (extracted.title) parts.push(extracted.title);
  else if (extracted.type) parts.push(extracted.type);
  if (parts.length > 0) {
    summary = parts.join(' ');
  } else if (extracted.summary) {
    summary = String(extracted.summary);
  } else if (extracted.merchant && extracted.total != null) {
    summary = `${extracted.merchant} - ${extracted.total}`;
  } else {
    // Last resort: pick any non-null string field
    const firstStr = Object.values(extracted).find(v => typeof v === 'string' && v.length > 0 && v.length < 100);
    summary = firstStr || 'unknown item';
  }
} catch (e) {
  summary = text.slice(0, 200);
  extracted = { _raw: text, _parse_error: String(e) };
}

let resolvedDomain = ctx.domain_hint;
if (!resolvedDomain && extracted && typeof extracted === "object" && extracted.best_domain_guess) {
  resolvedDomain = String(extracted.best_domain_guess);
}
if (!resolvedDomain) resolvedDomain = "unknown";

return [{
  json: {
    ...ctx,
    ai_summary:    summary,
    ai_extracted:  extracted,
    ai_model:      "claude-haiku-4-5-20251001",
    resolved_domain: resolvedDomain,
  }
}];
"""

# ============================================================
# Code: Plan move
# ============================================================
plan_move_code = r"""const ctx = $json;
const year = new Date().getFullYear();
const m = ctx.full_path.match(/\.[A-Za-z0-9]+$/);
const ext = m ? m[0].toLowerCase() : "";

const subdirs = {
  receipt:      `receipts/${year}`,
  tool:         "inventory/tools",
  saw_blade:    "inventory/saw_blades",
  wood:         "inventory/wood",
  album:        "inventory/albums",
  manual:       "manuals",
  house_room:   "house",
  cook_recipe:  "cook",
};
const subdir = subdirs[ctx.resolved_domain] || "inbox";
const newRel = `${subdir}/${ctx.asset_id}${ext}`;
const newFull = `/files/${newRel}`;

return [{
  json: {
    ...ctx,
    new_full_path: newFull,
    new_rel_path:  newRel,
    move_needed:   newFull !== ctx.full_path,
    move_payload:  { src: ctx.full_path, dst: newFull },
  }
}];
"""

# ============================================================
# HTTP: Move via filewriter
# ============================================================
http_move_node = {
    "method": "POST",
    "url": f"{FILEWRITER_URL}/move",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify($json.move_payload) }}",
    "options": {"timeout": 30000},
}

# After move: pass through context (we don't need the move response for anything else)
post_move_code = r"""const ctx = $('Plan Move').first().json;
return [{ json: ctx }];
"""

# ============================================================
# Postgres: update the row
# ============================================================
update_query = (
    "UPDATE files.assets SET "
    "  path         = '{{$json.new_full_path}}', "
    "  domain       = '{{$json.resolved_domain}}', "
    "  ai_summary   = {{$json.ai_summary === null ? 'NULL' : \"'\" + ($json.ai_summary || '').replace(/'/g, \"''\") + \"'\"}}, "
    "  ai_extracted = '{{JSON.stringify($json.ai_extracted || {}).replace(/'/g, \"''\")}}'::jsonb, "
    "  ai_model     = {{$json.ai_model === null ? 'NULL' : \"'\" + $json.ai_model + \"'\"}}, "
    "  processed_at = now() "
    "WHERE id = '{{$json.asset_id}}'::uuid"
)

format_response_code = r"""const ctx = $('Plan Move').first().json;
return [{
  json: {
    ok: true,
    asset_id:      ctx.asset_id,
    dedup:         false,
    domain:        ctx.resolved_domain || null,
    path:          ctx.new_full_path,
    ai_summary:    ctx.ai_summary || null,
    ai_extracted:  ctx.ai_extracted || null,
    duration_ms:   Date.now() - (ctx.started_at || Date.now()),
  }
}];
"""

dedup_response_code = r"""const ctx = $json;
return [{
  json: {
    ok: true,
    asset_id:      ctx.asset_id,
    dedup:         true,
    domain:        ctx.domain || null,
    path:          ctx.path || null,
    ai_summary:    ctx.ai_summary || null,
    ai_extracted:  ctx.ai_extracted || null,
    duration_ms:   Date.now() - (ctx.started_at || Date.now()),
  }
}];
"""


# ============================================================
# Build the workflow
# ============================================================
pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}
anthropic_creds = {"httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": "Anthropic API"}}

workflow = {
    "name": "Process Asset",
    "nodes": [
        {
            "parameters": {
                "path": "process-asset",
                "httpMethod": "POST",
                "responseMode": "lastNode",
                "options": {},
            },
            "id": "n-webhook",
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [200, 400],
            "webhookId": "process-asset-webhook",
        },
        {
            "parameters": {"inputSource": "passthrough"},
            "id": "n-exec-trigger",
            "name": "Execute Workflow Trigger",
            "type": "n8n-nodes-base.executeWorkflowTrigger",
            "typeVersion": 1.1,
            "position": [200, 600],
        },
        {
            "parameters": {"jsCode": validate_code},
            "id": "n-validate",
            "name": "Validate",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 400],
        },
        {
            "parameters": {
                "method": "POST",
                "url": f"{FILEWRITER_URL}/probe",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ path: $json.full_path }) }}",
                "options": {"timeout": 15000},
            },
            "id": "n-probe",
            "name": "Probe File",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [600, 400],
        },
        {
            "parameters": {"jsCode": parse_probe_code},
            "id": "n-parse-probe",
            "name": "Parse Probe",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [800, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": dedup_query,
                "options": {},
            },
            "id": "n-dedup",
            "name": "Dedup Query",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1000, 400],
            "credentials": pg,
            # Critical: when query returns 0 rows we still want one item to flow
            # downstream so the dedup-branch Code node runs.
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": dedup_branch_code},
            "id": "n-dedup-branch",
            "name": "Dedup Branch",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1200, 400],
        },
        {
            "parameters": if_dedup_conditions,
            "id": "n-if-dedup",
            "name": "Is Dedup?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [1400, 400],
        },
        {
            "parameters": {"jsCode": dedup_response_code},
            "id": "n-dedup-resp",
            "name": "Dedup Response",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1600, 240],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": insert_query,
                "options": {},
            },
            "id": "n-insert",
            "name": "Insert Asset",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1600, 560],
            "credentials": pg,
        },
        {
            "parameters": {"jsCode": post_insert_code},
            "id": "n-post-insert",
            "name": "Post Insert",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1800, 560],
        },
        {
            "parameters": {
                "method": "POST",
                "url": f"{FILEWRITER_URL}/read-base64",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ path: $json.full_path }) }}",
                "options": {"timeout": 30000},
            },
            "id": "n-readb64",
            "name": "Read Base64",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [2000, 560],
        },
        {
            "parameters": {"jsCode": build_prompt_code},
            "id": "n-build-prompt",
            "name": "Build Vision Prompt",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2200, 560],
        },
        {
            "parameters": if_vision_skip_conditions,
            "id": "n-if-skip",
            "name": "Skip Vision?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [2400, 560],
        },
        {
            "parameters": http_anthropic_node,
            "id": "n-anthropic",
            "name": "Anthropic Vision",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [2600, 720],
            "credentials": anthropic_creds,
        },
        {
            "parameters": {"jsCode": parse_vision_code},
            "id": "n-parse-vision",
            "name": "Parse Vision",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2800, 720],
        },
        {
            "parameters": {"jsCode": plan_move_code},
            "id": "n-plan-move",
            "name": "Plan Move",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3000, 560],
        },
        {
            "parameters": http_move_node,
            "id": "n-move",
            "name": "Move File",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [3200, 560],
        },
        {
            "parameters": {"jsCode": post_move_code},
            "id": "n-post-move",
            "name": "Post Move",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3400, 560],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": update_query,
                "options": {},
            },
            "id": "n-update",
            "name": "Update Asset",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [3600, 560],
            "credentials": pg,
        },
        {
            "parameters": {"jsCode": format_response_code},
            "id": "n-format",
            "name": "Format Response",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3800, 560],
        },
    ],
    "connections": {
        "Webhook":             {"main": [[{"node": "Validate",          "type": "main", "index": 0}]]},
        "Execute Workflow Trigger": {"main": [[{"node": "Validate",     "type": "main", "index": 0}]]},
        "Validate":            {"main": [[{"node": "Probe File",        "type": "main", "index": 0}]]},
        "Probe File":          {"main": [[{"node": "Parse Probe",       "type": "main", "index": 0}]]},
        "Parse Probe":         {"main": [[{"node": "Dedup Query",       "type": "main", "index": 0}]]},
        "Dedup Query":         {"main": [[{"node": "Dedup Branch",      "type": "main", "index": 0}]]},
        "Dedup Branch":        {"main": [[{"node": "Is Dedup?",         "type": "main", "index": 0}]]},
        "Is Dedup?": {
            "main": [
                [{"node": "Dedup Response", "type": "main", "index": 0}],
                [{"node": "Insert Asset",   "type": "main", "index": 0}],
            ]
        },
        "Insert Asset":        {"main": [[{"node": "Post Insert",        "type": "main", "index": 0}]]},
        "Post Insert":         {"main": [[{"node": "Read Base64",        "type": "main", "index": 0}]]},
        "Read Base64":         {"main": [[{"node": "Build Vision Prompt", "type": "main", "index": 0}]]},
        "Build Vision Prompt": {"main": [[{"node": "Skip Vision?",       "type": "main", "index": 0}]]},
        "Skip Vision?": {
            "main": [
                [{"node": "Plan Move",       "type": "main", "index": 0}],
                [{"node": "Anthropic Vision","type": "main", "index": 0}],
            ]
        },
        "Anthropic Vision":    {"main": [[{"node": "Parse Vision",      "type": "main", "index": 0}]]},
        "Parse Vision":        {"main": [[{"node": "Plan Move",         "type": "main", "index": 0}]]},
        "Plan Move":           {"main": [[{"node": "Move File",         "type": "main", "index": 0}]]},
        "Move File":           {"main": [[{"node": "Post Move",         "type": "main", "index": 0}]]},
        "Post Move":           {"main": [[{"node": "Update Asset",      "type": "main", "index": 0}]]},
        "Update Asset":        {"main": [[{"node": "Format Response",   "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}


with open('/home/michael/KiroProject/n8n-workflows/process-asset.json', 'w') as f:
    json.dump(workflow, f, indent=2)


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

existing = find_workflow_by_name("Process Asset")
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

if wf_id:
    act = api('POST', f'/workflows/{wf_id}/activate')
    print(f"Activate response: {act}")
    print(f"Webhook URL: {N8N_URL}/webhook/process-asset")
else:
    print("ERROR creating/updating:", resp)
