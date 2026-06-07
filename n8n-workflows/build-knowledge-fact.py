"""Create the Knowledge Memory workflow.

Two webhooks in one workflow:
  POST /webhook/remember  → save a fact into /knowledge/<topic>.md, deduped via Haiku
  POST /webhook/recall    → grep /knowledge/* for a query

Architecture:
  - Filewriter (http://filewriter:5001 from inside Docker network, or
    http://100.106.180.101:5001 from outside) handles all file I/O against /knowledge.
  - Haiku decides whether a new fact is already covered by existing content.
  - Topic is a free-form string like "finance/accounts" or "woodshop-tools".
    Normalized to lowercase, hyphenated, slashes preserved as subdirectories.

The Anthropic API key is read via $env.ANTHROPIC_API_KEY which is exposed to the
n8n container by docker-compose (works in HTTP Request nodes; not available in
Code nodes per project conventions).
"""
import json
import subprocess

from _config import API_KEY, N8N_URL

# Anthropic API key is provided by an n8n credential (httpHeaderAuth) named
# "Anthropic API". n8n blocks $env.* access in HTTP Request nodes, so we wire
# the API key through the credential mechanism instead.
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"
ANTHROPIC_CRED_NAME = "Anthropic API"

# Existing workflow ID (used on re-runs to PUT updates instead of creating dupes).
EXISTING_WORKFLOW_ID = "9fTh1G0THWgI6XB3"

# Filewriter is reachable from the n8n container at the host LAN IP. Same pattern
# the existing process-asset workflow uses.
FILEWRITER_URL = "http://100.106.180.101:5001"

# Model selection. Haiku is fine for "is this fact already covered?" reasoning.
HAIKU_MODEL = "claude-haiku-4-5-20251001"

# ---- JS code blocks --------------------------------------------------------

# Normalize the topic into a safe relative path. Allows letters, numbers,
# hyphens, underscores, and forward-slashes (for sub-dirs). Anything else is
# replaced with a hyphen. Forces lowercase. Strips leading/trailing slashes.
normalize_remember_code = r"""const body = $input.first().json.body || $input.first().json;

const topicRaw = body.topic;
const factRaw = body.fact;

if (!topicRaw || typeof topicRaw !== 'string' || topicRaw.trim().length === 0) {
  return [{ json: { valid: false, error: 'Missing required parameter: topic' } }];
}
if (!factRaw || typeof factRaw !== 'string' || factRaw.trim().length === 0) {
  return [{ json: { valid: false, error: 'Missing required parameter: fact' } }];
}

const fact = factRaw.trim();

// Normalize the topic to a filesystem-safe slug. Spaces → hyphens, uppercase → lowercase,
// strip anything that isn't [a-z0-9_/-]. Collapse repeated hyphens. Trim slashes.
let topic = topicRaw
  .trim()
  .toLowerCase()
  .replace(/\s+/g, '-')
  .replace(/[^a-z0-9_/-]+/g, '-')
  .replace(/-+/g, '-')
  .replace(/^[/-]+|[/-]+$/g, '');

if (topic.length === 0) {
  return [{ json: { valid: false, error: 'Topic normalized to empty string. Use letters, numbers, hyphens, or slashes.' } }];
}

const path = '/knowledge/' + topic + '.md';
const today = new Date().toISOString().slice(0, 10);

return [{ json: { valid: true, topic, path, fact, today } }];"""

decide_dedup_code = r"""// Read result returned from filewriter /read-text.
const validated = $('Validate Remember').first().json;
const readResp = $input.first().json;

const exists = readResp.exists === true;
const content = (readResp.content || '').trim();
const isEmpty = content.length === 0;

return [{ json: Object.assign({}, validated, {
  exists,
  existing_content: content,
  needs_dedup: exists && !isEmpty
}) }];"""

build_dedup_prompt_code = r"""const ctx = $input.first().json;

const systemPrompt = "You are a deduplication classifier for a personal knowledge base. " +
  "Given EXISTING knowledge about a topic and a NEW FACT, decide whether the new fact is " +
  "already substantively covered by the existing content. Be strict: paraphrases of the " +
  "same fact ARE duplicates. Conflicting facts (e.g., 'Ally is emergency fund' vs. " +
  "'Marcus is emergency fund') are NOT duplicates — they should both be saved so the " +
  "history is preserved. New details that add specificity are NOT duplicates. " +
  "Respond with ONLY a JSON object, no prose, no markdown fences: " +
  "{\"covered\": boolean, \"reason\": \"short explanation\", \"conflicts_with\": null or \"the conflicting existing line\"}";

const userPrompt = "TOPIC: " + ctx.topic + "\n\n" +
  "EXISTING KNOWLEDGE:\n" + ctx.existing_content + "\n\n" +
  "NEW FACT: " + ctx.fact + "\n\n" +
  "Is the new fact already covered? Return JSON only.";

return [{ json: Object.assign({}, ctx, {
  system_prompt: systemPrompt,
  user_prompt: userPrompt
}) }];"""

parse_dedup_code = r"""const ctx = $('Build Dedup Prompt').first().json;
const resp = $input.first().json;

// Extract Haiku's text response.
let text = '';
try {
  text = (resp.content && resp.content[0] && resp.content[0].text) || '';
} catch (e) {
  text = '';
}

// Strip code fences if any (Haiku occasionally adds them despite instructions).
text = text.trim().replace(/^```(?:json)?\s*/i, '').replace(/```\s*$/, '').trim();

let decision = { covered: false, reason: 'parse_failed', conflicts_with: null };
try {
  decision = JSON.parse(text);
} catch (e) {
  // On parse failure, default to NOT covered (safer to save a duplicate than lose a fact).
  decision = { covered: false, reason: 'haiku_response_unparseable: ' + text.slice(0, 200), conflicts_with: null };
}

return [{ json: Object.assign({}, ctx, {
  dedup_decision: decision,
  should_save: !decision.covered
}) }];"""

# Branch context for the "no dedup needed, save directly" path.
direct_save_ctx_code = r"""const ctx = $input.first().json;
return [{ json: Object.assign({}, ctx, {
  dedup_decision: { covered: false, reason: 'first_entry_for_topic', conflicts_with: null },
  should_save: true
}) }];"""

build_append_payload_code = r"""const ctx = $input.first().json;

// Format: "- [YYYY-MM-DD] fact text"
const line = '- [' + ctx.today + '] ' + ctx.fact;

// If the file is brand new (didn't exist before), prepend a header.
const header = ctx.exists ? '' : '# ' + ctx.topic.replace(/\//g, ' / ') + '\n\n';

return [{ json: Object.assign({}, ctx, {
  append_payload: { path: ctx.path, content: header + line }
}) }];"""

format_remember_response_code = r"""const ctx = $input.first().json;
const decision = ctx.dedup_decision || {};

if (ctx.should_save) {
  return [{ json: {
    success: true,
    saved: true,
    topic: ctx.topic,
    path: ctx.path,
    fact: ctx.fact,
    note: decision.reason,
    conflicts_with: decision.conflicts_with || null
  } }];
}

return [{ json: {
  success: true,
  saved: false,
  topic: ctx.topic,
  path: ctx.path,
  fact: ctx.fact,
  note: 'Fact appears to already be covered by existing content. ' + (decision.reason || ''),
  conflicts_with: decision.conflicts_with || null
} }];"""

invalid_remember_code = r"""const v = $('Validate Remember').first().json;
return [{ json: { success: false, error: v.error } }];"""

# --- Recall ----------------------------------------------------------------

normalize_recall_code = r"""const body = $input.first().json.body || $input.first().json;
const queryRaw = body.query;

if (!queryRaw || typeof queryRaw !== 'string' || queryRaw.trim().length === 0) {
  return [{ json: { valid: false, error: 'Missing required parameter: query' } }];
}

return [{ json: {
  valid: true,
  query: queryRaw.trim(),
  search_payload: {
    root: '/knowledge',
    query: queryRaw.trim(),
    case_insensitive: true,
    extensions: ['.md', '.txt'],
    max_results: 100,
    mode: 'smart'
  }
} }];"""

format_recall_response_code = r"""const ctx = $('Validate Recall').first().json;
const resp = $input.first().json;

if (!resp.ok) {
  return [{ json: { success: false, error: resp.error || 'search_failed' } }];
}

const matches = resp.matches || [];

// Group by file for nicer presentation.
const byFile = {};
for (const m of matches) {
  if (!byFile[m.file]) byFile[m.file] = [];
  byFile[m.file].push({ line_number: m.line_number, line: m.line });
}

// Convert to an array of {topic, lines} where topic is derived from the file path.
const groups = Object.keys(byFile).map(file => {
  const topic = file.replace(/^\/knowledge\//, '').replace(/\.md$|\.txt$/, '');
  return { topic, file, lines: byFile[file] };
});

return [{ json: {
  success: true,
  query: ctx.query,
  match_count: matches.length,
  truncated: resp.truncated === true,
  results: groups
} }];"""

invalid_recall_code = r"""const v = $('Validate Recall').first().json;
return [{ json: { success: false, error: v.error } }];"""

# ---- HTTP node parameter blocks ------------------------------------------

filewriter_read_node = {
    "method": "POST",
    "url": f"{FILEWRITER_URL}/read-text",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify({ path: $json.path }) }}",
    "options": {"timeout": 10000},
}

filewriter_append_node = {
    "method": "POST",
    "url": f"{FILEWRITER_URL}/append",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify($json.append_payload) }}",
    "options": {"timeout": 10000},
}

filewriter_search_node = {
    "method": "POST",
    "url": f"{FILEWRITER_URL}/search",
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": "={{ JSON.stringify($json.search_payload) }}",
    "options": {"timeout": 10000},
}

# Anthropic Haiku call. The API key is supplied via the "Anthropic API"
# httpHeaderAuth credential (n8n blocks $env access in HTTP Request nodes).
anthropic_dedup_node = {
    "url": "https://api.anthropic.com/v1/messages",
    "method": "POST",
    "authentication": "predefinedCredentialType",
    "nodeCredentialType": "httpHeaderAuth",
    "sendHeaders": True,
    "headerParameters": {
        "parameters": [
            {"name": "anthropic-version", "value": "2023-06-01"},
            {"name": "content-type", "value": "application/json"},
        ]
    },
    "sendBody": True,
    "specifyBody": "json",
    "jsonBody": (
        "={{ JSON.stringify({ "
        f"model: '{HAIKU_MODEL}', "
        "max_tokens: 256, "
        "system: $json.system_prompt, "
        "messages: [{ role: 'user', content: $json.user_prompt }] "
        "}) }}"
    ),
    "options": {"timeout": 30000},
}

# ---- Build workflow --------------------------------------------------------

workflow = {
    "name": "Knowledge Memory",
    "description": "Personal knowledge base. /webhook/remember saves facts to /knowledge/<topic>.md (Haiku-deduped). /webhook/recall greps /knowledge for a query.",
    "nodes": [
        # ===== Remember branch =====
        {
            "parameters": {"path": "remember", "httpMethod": "POST", "responseMode": "lastNode", "options": {}},
            "id": "wh-remember",
            "name": "Webhook Remember",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [200, 300],
            "webhookId": "remember-webhook",
        },
        {
            "parameters": {"jsCode": normalize_remember_code},
            "id": "validate-remember",
            "name": "Validate Remember",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 300],
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{
                        "id": "valid-remember",
                        "leftValue": "={{ $json.valid }}",
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true"},
                    }],
                    "combinator": "and",
                },
                "options": {},
            },
            "id": "if-valid-remember",
            "name": "IF Valid Remember",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [600, 300],
        },
        {
            "parameters": {"jsCode": invalid_remember_code},
            "id": "invalid-remember",
            "name": "Invalid Remember",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [800, 460],
        },
        {
            "parameters": filewriter_read_node,
            "id": "read-existing",
            "name": "Read Existing",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [800, 200],
        },
        {
            "parameters": {"jsCode": decide_dedup_code},
            "id": "decide-dedup",
            "name": "Decide Dedup",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1000, 200],
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{
                        "id": "needs-dedup",
                        "leftValue": "={{ $json.needs_dedup }}",
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true"},
                    }],
                    "combinator": "and",
                },
                "options": {},
            },
            "id": "if-needs-dedup",
            "name": "IF Needs Dedup",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [1200, 200],
        },
        # Branch: dedup needed
        {
            "parameters": {"jsCode": build_dedup_prompt_code},
            "id": "build-prompt",
            "name": "Build Dedup Prompt",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1400, 100],
        },
        {
            "parameters": anthropic_dedup_node,
            "id": "haiku-dedup",
            "name": "Haiku Dedup",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1600, 100],
            "credentials": {
                "httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": ANTHROPIC_CRED_NAME}
            },
        },
        {
            "parameters": {"jsCode": parse_dedup_code},
            "id": "parse-dedup",
            "name": "Parse Dedup",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1800, 100],
        },
        # Branch: no dedup needed (file empty or doesn't exist)
        {
            "parameters": {"jsCode": direct_save_ctx_code},
            "id": "direct-save",
            "name": "Direct Save Ctx",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1400, 300],
        },
        # Merge both branches
        {
            "parameters": {},
            "id": "merge-save",
            "name": "Merge Save Decision",
            "type": "n8n-nodes-base.merge",
            "typeVersion": 3,
            "position": [2000, 200],
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{
                        "id": "should-save",
                        "leftValue": "={{ $json.should_save }}",
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true"},
                    }],
                    "combinator": "and",
                },
                "options": {},
            },
            "id": "if-should-save",
            "name": "IF Should Save",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [2200, 200],
        },
        {
            "parameters": {"jsCode": build_append_payload_code},
            "id": "build-append",
            "name": "Build Append Payload",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2400, 100],
        },
        {
            "parameters": filewriter_append_node,
            "id": "do-append",
            "name": "Append Fact",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [2600, 100],
        },
        # Carry context forward past the HTTP append (its response replaces $json).
        {
            "parameters": {
                "jsCode": "return [{ json: $('Build Append Payload').first().json }];"
            },
            "id": "carry-after-append",
            "name": "Carry Context",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2800, 100],
        },
        {
            "parameters": {"jsCode": format_remember_response_code},
            "id": "format-remember",
            "name": "Format Remember Response",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3000, 200],
        },

        # ===== Recall branch =====
        {
            "parameters": {"path": "recall", "httpMethod": "POST", "responseMode": "lastNode", "options": {}},
            "id": "wh-recall",
            "name": "Webhook Recall",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [200, 800],
            "webhookId": "recall-webhook",
        },
        {
            "parameters": {"jsCode": normalize_recall_code},
            "id": "validate-recall",
            "name": "Validate Recall",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 800],
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{
                        "id": "valid-recall",
                        "leftValue": "={{ $json.valid }}",
                        "rightValue": True,
                        "operator": {"type": "boolean", "operation": "true"},
                    }],
                    "combinator": "and",
                },
                "options": {},
            },
            "id": "if-valid-recall",
            "name": "IF Valid Recall",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [600, 800],
        },
        {
            "parameters": {"jsCode": invalid_recall_code},
            "id": "invalid-recall",
            "name": "Invalid Recall",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [800, 950],
        },
        {
            "parameters": filewriter_search_node,
            "id": "do-search",
            "name": "Search Knowledge",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [800, 700],
        },
        {
            "parameters": {"jsCode": format_recall_response_code},
            "id": "format-recall",
            "name": "Format Recall Response",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1000, 700],
        },
    ],
    "connections": {
        # Remember
        "Webhook Remember": {"main": [[{"node": "Validate Remember", "type": "main", "index": 0}]]},
        "Validate Remember": {"main": [[{"node": "IF Valid Remember", "type": "main", "index": 0}]]},
        "IF Valid Remember": {"main": [
            [{"node": "Read Existing", "type": "main", "index": 0}],
            [{"node": "Invalid Remember", "type": "main", "index": 0}],
        ]},
        "Read Existing": {"main": [[{"node": "Decide Dedup", "type": "main", "index": 0}]]},
        "Decide Dedup": {"main": [[{"node": "IF Needs Dedup", "type": "main", "index": 0}]]},
        "IF Needs Dedup": {"main": [
            [{"node": "Build Dedup Prompt", "type": "main", "index": 0}],
            [{"node": "Direct Save Ctx", "type": "main", "index": 0}],
        ]},
        "Build Dedup Prompt": {"main": [[{"node": "Haiku Dedup", "type": "main", "index": 0}]]},
        "Haiku Dedup": {"main": [[{"node": "Parse Dedup", "type": "main", "index": 0}]]},
        "Parse Dedup": {"main": [[{"node": "Merge Save Decision", "type": "main", "index": 0}]]},
        "Direct Save Ctx": {"main": [[{"node": "Merge Save Decision", "type": "main", "index": 1}]]},
        "Merge Save Decision": {"main": [[{"node": "IF Should Save", "type": "main", "index": 0}]]},
        "IF Should Save": {"main": [
            [{"node": "Build Append Payload", "type": "main", "index": 0}],
            [{"node": "Format Remember Response", "type": "main", "index": 0}],
        ]},
        "Build Append Payload": {"main": [[{"node": "Append Fact", "type": "main", "index": 0}]]},
        "Append Fact": {"main": [[{"node": "Carry Context", "type": "main", "index": 0}]]},
        "Carry Context": {"main": [[{"node": "Format Remember Response", "type": "main", "index": 0}]]},

        # Recall
        "Webhook Recall": {"main": [[{"node": "Validate Recall", "type": "main", "index": 0}]]},
        "Validate Recall": {"main": [[{"node": "IF Valid Recall", "type": "main", "index": 0}]]},
        "IF Valid Recall": {"main": [
            [{"node": "Search Knowledge", "type": "main", "index": 0}],
            [{"node": "Invalid Recall", "type": "main", "index": 0}],
        ]},
        "Search Knowledge": {"main": [[{"node": "Format Recall Response", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}

with open("/home/michael/KiroProject/n8n-workflows/knowledge-memory.json", "w") as f:
    json.dump(workflow, f, indent=2)
print("Saved knowledge-memory.json")


def api(method, path, data=None):
    cmd = ["curl", "-s", "-X", method,
           "-H", f"X-N8N-API-KEY: {API_KEY}",
           "-H", "Content-Type: application/json"]
    if data is not None:
        cmd.extend(["-d", json.dumps(data)])
    cmd.append(f"{N8N_URL}/api/v1{path}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout) if r.stdout else {}


payload = {k: workflow[k] for k in ["name", "nodes", "connections", "settings"]}

# Try update first; fall back to create if the workflow doesn't exist yet.
if EXISTING_WORKFLOW_ID:
    resp = api("PUT", f"/workflows/{EXISTING_WORKFLOW_ID}", payload)
    if resp.get("id"):
        print(f"Updated workflow: {resp.get('id')} active={resp.get('active')}")
        if not resp.get("active"):
            act = api("POST", f"/workflows/{resp['id']}/activate")
            print(f"Re-activated: {act.get('active')}")
    else:
        print(f"Update failed: {resp.get('message', resp)}")
else:
    resp = api("POST", "/workflows", payload)
    wf_id = resp.get("id")
    print(f"Created workflow: {wf_id}")
    if wf_id:
        act = api("POST", f"/workflows/{wf_id}/activate")
        print(f"Active: {act.get('active')}")
    elif "message" in resp:
        print(f"Error: {resp['message'][:500]}")
