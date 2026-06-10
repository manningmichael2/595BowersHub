import os
"""
Patch the AI Inbox Classifier workflow to process up to 10 emails per run
instead of just 1. Fixes the .first() references that prevented batch processing.
"""
import json
import subprocess

API_KEY = os.environ.get("N8N_API_KEY", "")  # ROTATED — set via env var
N8N_URL = "http://100.106.180.101:5678"
WORKFLOW_ID = "quNNHEhPI12UXxpp"

with open("/home/michael/KiroProject/classifier_workflow.json") as f:
    wf = json.load(f)

nodes = wf["nodes"]

# --- Patch Filter Unclassified: limit to 10 items ---
for node in nodes:
    if node["name"] == "Filter Unclassified":
        node["parameters"]["jsCode"] = r"""// Get the set of already-classified message IDs from the Postgres query
const classifiedRows = $('Get Classified IDs').all().map(i => i.json.message_id).filter(Boolean);
const classifiedSet = new Set(classifiedRows);

// Get all emails from the fetch step
const emails = $('Fetch Emails').all().map(i => i.json);

// Filter to only unclassified emails, limit to 10 per run
const unclassified = emails.filter(e => e.message_id && !classifiedSet.has(e.message_id)).slice(0, 10);

if (unclassified.length === 0) {
  return [{ json: { note: "All emails already classified", count: 0, _skip: true } }];
}

// Emit one item per unclassified email — downstream nodes process each individually
return unclassified.map(email => ({ json: email }));
"""
        # Must be runOnceForAllItems since it references multiple upstream nodes
        node["parameters"]["mode"] = "runOnceForAllItems"

    elif node["name"] == "Build Classifier Prompt":
        # Fix: use $json (current item) instead of .first()
        node["parameters"]["jsCode"] = r"""// Skip if upstream said nothing to process
if ($json._skip) return [{ json: { _skip: true } }];

const email = $json;
const labelRows = $('Get Existing Labels').all().map(i => i.json.label);
const existingLabels = labelRows.length > 0 ? labelRows.join(', ') : 'AI-Tags/Receipts, AI-Tags/Bills, AI-Tags/Subscriptions, AI-Tags/Shipping, AI-Tags/Finance, AI-Tags/Pets, AI-Tags/House, AI-Tags/Travel, AI-Tags/Social, AI-Tags/Newsletters, AI-Tags/Spam-ish, AI-Tags/Action-Required';

const subject = email.subject || '(no subject)';
const from = email.from_address || email.from_name || 'unknown';
const body = (email.body_text || '').slice(0, 1500);

const prompt = `Classify this email by applying 1-3 labels. Use the "AI-Tags/" prefix for all labels.

RULES:
- Reuse existing labels when they fit. Only create a new label if nothing existing applies.
- If this is a purchase receipt, order confirmation, or payment confirmation, you MUST include "AI-Tags/Receipts" as one of the labels.
- Labels should be short, consistent, and descriptive (e.g., "AI-Tags/Pets", "AI-Tags/Travel").
- Use Title Case after the prefix (e.g., "AI-Tags/Home-Improvement" not "AI-Tags/home improvement").
- Use hyphens for multi-word labels (e.g., "AI-Tags/Action-Required").

Previously used labels: ${existingLabels}

EMAIL:
From: ${from}
Subject: ${subject}
Body preview: ${body}

Return ONLY a JSON object: {"labels": ["AI-Tags/...", ...]}`;

const payload = {
  model: "claude-haiku-4-5-20251001",
  max_tokens: 256,
  messages: [{ role: "user", content: prompt }]
};

return [{ json: { ...email, haiku_payload: payload } }];
"""

    elif node["name"] == "Parse Classification":
        # Fix: use $('Build Classifier Prompt').item for per-item context
        node["parameters"]["jsCode"] = r"""// Skip if upstream said nothing to process
if ($json._skip) return [{ json: { _skip: true } }];

// In per-item mode, HTTP Request output replaces $json with the API response.
// Get the email context from the Build Classifier Prompt node's matching item.
const ctx = $('Build Classifier Prompt').item.json;
const resp = $json;

let text = "";
try { text = (resp.content && resp.content[0] && resp.content[0].text) || ""; }
catch (e) { /* fall through */ }

text = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();

let labels = [];
try {
  const parsed = JSON.parse(text);
  labels = Array.isArray(parsed.labels) ? parsed.labels : [];
} catch (e) {
  const matches = text.match(/AI-Tags\/[A-Za-z0-9-]+/g);
  labels = matches || [];
}

// Guardrail: ensure labels are properly formatted
labels = labels
  .filter(l => typeof l === 'string' && l.startsWith('AI-Tags/'))
  .slice(0, 3);

if (labels.length === 0) {
  labels = ['AI-Tags/Newsletters'];
}

return [{ json: { ...ctx, labels: labels } }];
"""

    elif node["name"] == "Apply Labels":
        # Already uses $json correctly — add _skip check
        existing_code = node["parameters"]["jsCode"]
        node["parameters"]["jsCode"] = "// Skip if upstream said nothing to process\nif ($json._skip) return [{ json: { _skip: true } }];\n\n" + existing_code

    elif node["name"] == "Record Classified":
        # Fix the SQL to use $json (current item) instead of referencing Apply Labels .first()
        node["parameters"]["query"] = (
            "INSERT INTO public.email_classified (message_id, labels) "
            "VALUES ('{{$json.message_id}}', "
            "ARRAY[{{$json.labels.map(l => \"'\" + l.replace(/'/g, \"''\") + \"'\").join(',')}}]::text[]) "
            "ON CONFLICT (message_id) DO NOTHING"
        )

    elif node["name"] == "Prep Label Upsert":
        # Fix: use $json instead of $('Apply Labels').first().json
        node["parameters"]["jsCode"] = r"""// Skip if upstream said nothing to process
if ($json._skip) return [{ json: { _skip: true, upsert_sql: 'SELECT 1' } }];

const ctx = $json;
const labels = ctx.labels || [];

if (labels.length === 0) {
  return [{ json: { ...ctx, upsert_sql: 'SELECT 1' } }];
}

const queries = labels.map(label => {
  const escaped = label.replace(/'/g, "''");
  return `INSERT INTO public.email_labels (label, times_used, last_used) VALUES ('${escaped}', 1, now()) ON CONFLICT (label) DO UPDATE SET times_used = email_labels.times_used + 1, last_used = now()`;
});

return [{ json: { ...ctx, upsert_queries: queries, upsert_sql: queries.join('; ') } }];
"""

    elif node["name"] == "Summarize":
        node["parameters"]["jsCode"] = r"""if ($json._skip) return [{ json: { ok: true, note: "No emails to classify this run" } }];

const ctx = $json;
return [{
  json: {
    ok: true,
    message_id: ctx.message_id,
    subject: ctx.subject,
    from: ctx.from_address || ctx.from_name,
    labels: ctx.labels,
    archived: ctx.archived || false,
  }
}];
"""

# Now PUT the updated workflow back
# First deactivate, then update, then reactivate
print("Deactivating workflow...")
r = subprocess.run(
    ["curl", "-s", "-X", "POST",
     f"{N8N_URL}/api/v1/workflows/{WORKFLOW_ID}/deactivate",
     "-H", f"X-N8N-API-KEY: {API_KEY}"],
    capture_output=True, text=True
)
print(f"  Deactivate: {json.loads(r.stdout).get('active') if r.stdout else 'failed'}")

# Prepare the update payload (only nodes and connections)
update_payload = {
    "nodes": wf["nodes"],
    "connections": wf["connections"],
    "settings": wf.get("settings", {}),
    "name": wf["name"],
}

print("Updating workflow...")
r = subprocess.run(
    ["curl", "-s", "-X", "PUT",
     f"{N8N_URL}/api/v1/workflows/{WORKFLOW_ID}",
     "-H", f"X-N8N-API-KEY: {API_KEY}",
     "-H", "Content-Type: application/json",
     "-d", json.dumps(update_payload)],
    capture_output=True, text=True
)
resp = json.loads(r.stdout) if r.stdout else {}
if "id" in resp:
    print(f"  ✅ Updated: {resp['name']} (ID: {resp['id']})")
else:
    print(f"  ❌ Error: {r.stdout[:500]}")
    exit(1)

print("Reactivating workflow...")
r = subprocess.run(
    ["curl", "-s", "-X", "POST",
     f"{N8N_URL}/api/v1/workflows/{WORKFLOW_ID}/activate",
     "-H", f"X-N8N-API-KEY: {API_KEY}"],
    capture_output=True, text=True
)
resp = json.loads(r.stdout) if r.stdout else {}
print(f"  Active: {resp.get('active')}")
print("\nDone! Workflow now processes up to 10 emails per run.")
