import os
"""
Rebuild the AI Inbox Classifier workflow to process up to 10 emails per run.

Strategy: Merge the Haiku call + parse into a single Code node that uses
this.helpers.httpRequest internally. This avoids the n8n issue where HTTP
Request nodes lose input context in per-item mode.

Flow:
  Cron → Fetch Emails → Get Classified IDs → Filter Unclassified (max 10)
       → Get Existing Labels → Classify + Apply (single code node per item)
       → Record + Upsert (single code node per item)
"""
import json
import subprocess

API_KEY = os.environ.get("N8N_API_KEY", "")  # ROTATED — set via env var
N8N_URL = "http://100.106.180.101:5678"
WORKFLOW_ID = "quNNHEhPI12UXxpp"

POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"

pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}
anthropic_creds = {"httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": "Anthropic API"}}

# ============================================================
# Node code blocks
# ============================================================

fetch_emails_code = r"""// Fetch recent emails — look back 7 days to catch backlog.
const response = await this.helpers.httpRequest({
  method: 'POST',
  url: 'http://100.106.180.101:5001/imap/fetch-recent',
  body: {
    folder: "INBOX",
    since_minutes: 10080,
    limit: 50,
    include_body: true,
    body_max_chars: 2000
  },
  json: true,
});

if (!response || !response.ok || !response.emails || response.emails.length === 0) {
  return [{ json: { _done: true, note: "No emails to process" } }];
}

return response.emails.map(email => ({ json: email }));
"""

filter_unclassified_code = r"""// Get already-classified message IDs
const classifiedRows = $('Get Classified IDs').all().map(i => i.json.message_id).filter(Boolean);
const classifiedSet = new Set(classifiedRows);

// Get all emails from fetch
const emails = $('Fetch Emails').all().map(i => i.json);

// Filter and limit to 10
const unclassified = emails.filter(e => e.message_id && !classifiedSet.has(e.message_id)).slice(0, 10);

if (unclassified.length === 0) {
  return [{ json: { _done: true, note: "All emails already classified", count: 0 } }];
}

return unclassified.map(email => ({ json: email }));
"""

# This is the key node — does classification + label application + recording all in one
# per-item Code node. No context loss between nodes.
classify_and_apply_code = r"""// Skip the "done" sentinel item
if ($json._done) return [{ json: $json }];

const email = $json;
const labelRows = $('Get Existing Labels').all().map(i => i.json.label);
const existingLabels = labelRows.length > 0 ? labelRows.join(', ') : 'AI-Tags/Receipts, AI-Tags/Bills, AI-Tags/Subscriptions, AI-Tags/Shipping, AI-Tags/Finance, AI-Tags/Pets, AI-Tags/House, AI-Tags/Travel, AI-Tags/Social, AI-Tags/Newsletters, AI-Tags/Spam-ish, AI-Tags/Action-Required';

const subject = email.subject || '(no subject)';
const from = email.from_address || email.from_name || 'unknown';
const body = (email.body_text || '').slice(0, 1500);

// --- Step 1: Call Haiku for classification ---
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

let labels = [];
try {
  const resp = await this.helpers.httpRequestWithAuthentication.call(this, 'httpHeaderAuth', {
    method: 'POST',
    url: 'https://api.anthropic.com/v1/messages',
    headers: {
      'Content-Type': 'application/json',
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 256,
      messages: [{ role: "user", content: prompt }]
    }),
    json: true,
  });

  let text = (resp.content && resp.content[0] && resp.content[0].text) || "";
  text = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();

  try {
    const parsed = JSON.parse(text);
    labels = Array.isArray(parsed.labels) ? parsed.labels : [];
  } catch (e) {
    const matches = text.match(/AI-Tags\/[A-Za-z0-9-]+/g);
    labels = matches || [];
  }
} catch (apiErr) {
  // If Haiku fails, skip this email — don't block the batch
  return [{ json: { ...email, labels: [], error: apiErr.message, _failed: true } }];
}

// Guardrail: format and cap
labels = labels.filter(l => typeof l === 'string' && l.startsWith('AI-Tags/')).slice(0, 3);
if (labels.length === 0) labels = ['AI-Tags/Newsletters'];

// --- Step 2: Apply labels via IMAP ---
const AUTO_ARCHIVE_LABELS = new Set([
  'AI-Tags/Newsletters', 'AI-Tags/Spam-ish', 'AI-Tags/Shipping',
  'AI-Tags/Receipts', 'AI-Tags/Subscriptions',
]);

const labelResults = [];
for (const label of labels) {
  try {
    const data = await this.helpers.httpRequest({
      method: 'POST',
      url: 'http://100.106.180.101:5001/imap/add-label',
      body: { source_folder: "INBOX", uid: email.uid, label: label },
      json: true,
    });
    labelResults.push({ label, ok: data.ok, error: data.error || null });
  } catch (e) {
    labelResults.push({ label, ok: false, error: e.message });
  }
}

// Auto-archive if ALL labels are archivable
const allArchivable = labels.every(l => AUTO_ARCHIVE_LABELS.has(l));
let archived = false;
if (allArchivable && email.uid) {
  try {
    const archiveData = await this.helpers.httpRequest({
      method: 'POST',
      url: 'http://100.106.180.101:5001/imap/archive',
      body: { uid: email.uid },
      json: true,
    });
    archived = archiveData.ok || false;
  } catch (e) { archived = false; }
}

return [{ json: {
  message_id: email.message_id,
  subject: email.subject,
  from: email.from_address || email.from_name,
  uid: email.uid,
  labels: labels,
  label_results: labelResults,
  archived: archived,
}}];
"""

# Record in Postgres + upsert label counts — also a single code node
record_code = r"""// Skip sentinel or failed items
if ($json._done || $json._failed) return [{ json: $json }];

const ctx = $json;
const msgId = (ctx.message_id || '').replace(/'/g, "''");
const labelsArr = (ctx.labels || []).map(l => "'" + l.replace(/'/g, "''") + "'").join(',');

// Record classification
try {
  await this.helpers.httpRequest({
    method: 'POST',
    url: 'http://100.106.180.101:5001/imap/mark-read',
    body: { folder: "INBOX", uid: ctx.uid },
    json: true,
  });
} catch (e) { /* non-critical */ }

return [{ json: {
  ok: true,
  message_id: ctx.message_id,
  subject: ctx.subject,
  from: ctx.from,
  labels: ctx.labels,
  archived: ctx.archived,
}}];
"""

# We'll use Postgres nodes for the actual DB writes since they handle credentials
record_classified_query = (
    "INSERT INTO public.email_classified (message_id, labels) "
    "VALUES ('{{$json.message_id}}', "
    "ARRAY[{{$json.labels.map(l => \"'\" + l.replace(/'/g, \"''\") + \"'\").join(',')}}]::text[]) "
    "ON CONFLICT (message_id) DO NOTHING"
)

upsert_labels_code = r"""if ($json._done || $json._failed) return [{ json: { upsert_sql: 'SELECT 1' } }];

const labels = $json.labels || [];
if (labels.length === 0) return [{ json: { upsert_sql: 'SELECT 1' } }];

const queries = labels.map(label => {
  const escaped = label.replace(/'/g, "''");
  return `INSERT INTO public.email_labels (label, times_used, last_used) VALUES ('${escaped}', 1, now()) ON CONFLICT (label) DO UPDATE SET times_used = email_labels.times_used + 1, last_used = now()`;
});

return [{ json: { ...($json), upsert_sql: queries.join('; ') } }];
"""

# ============================================================
# Build workflow
# ============================================================
workflow = {
    "name": "AI Inbox Classifier",
    "nodes": [
        {
            "parameters": {"rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}},
            "id": "n-cron",
            "name": "Every 5 Minutes",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [200, 400],
        },
        {
            "parameters": {"jsCode": fetch_emails_code, "mode": "runOnceForAllItems"},
            "id": "n-fetch",
            "name": "Fetch Emails",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "SELECT message_id FROM public.email_classified WHERE classified_at > now() - interval '8 days'",
                "options": {},
            },
            "id": "n-check",
            "name": "Get Classified IDs",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [600, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": filter_unclassified_code, "mode": "runOnceForAllItems"},
            "id": "n-filter",
            "name": "Filter Unclassified",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [800, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "SELECT label FROM public.email_labels ORDER BY times_used DESC LIMIT 50",
                "options": {},
            },
            "id": "n-labels",
            "name": "Get Existing Labels",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1000, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        # The big combined node: classify + apply labels + archive
        {
            "parameters": {"jsCode": classify_and_apply_code},
            "id": "n-classify",
            "name": "Classify and Apply",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1200, 400],
            "credentials": anthropic_creds,
        },
        # Record in DB
        {
            "parameters": {
                "operation": "executeQuery",
                "query": record_classified_query,
                "options": {},
            },
            "id": "n-record",
            "name": "Record Classified",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1400, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        # Upsert label counts
        {
            "parameters": {"jsCode": upsert_labels_code},
            "id": "n-upsert-prep",
            "name": "Prep Label Upsert",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1600, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "{{$json.upsert_sql}}",
                "options": {},
            },
            "id": "n-upsert",
            "name": "Upsert Labels",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1800, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
    ],
    "connections": {
        "Every 5 Minutes": {"main": [[{"node": "Fetch Emails", "type": "main", "index": 0}]]},
        "Fetch Emails": {"main": [[{"node": "Get Classified IDs", "type": "main", "index": 0}]]},
        "Get Classified IDs": {"main": [[{"node": "Filter Unclassified", "type": "main", "index": 0}]]},
        "Filter Unclassified": {"main": [[{"node": "Get Existing Labels", "type": "main", "index": 0}]]},
        "Get Existing Labels": {"main": [[{"node": "Classify and Apply", "type": "main", "index": 0}]]},
        "Classify and Apply": {"main": [[{"node": "Record Classified", "type": "main", "index": 0}]]},
        "Record Classified": {"main": [[{"node": "Prep Label Upsert", "type": "main", "index": 0}]]},
        "Prep Label Upsert": {"main": [[{"node": "Upsert Labels", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}

# ============================================================
# Deploy
# ============================================================
update_payload = {
    "nodes": workflow["nodes"],
    "connections": workflow["connections"],
    "settings": workflow["settings"],
    "name": workflow["name"],
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

print("Activating workflow...")
r = subprocess.run(
    ["curl", "-s", "-X", "POST",
     f"{N8N_URL}/api/v1/workflows/{WORKFLOW_ID}/activate",
     "-H", f"X-N8N-API-KEY: {API_KEY}"],
    capture_output=True, text=True
)
resp = json.loads(r.stdout) if r.stdout else {}
if resp.get("active"):
    print(f"  ✅ Active!")
else:
    print(f"  ⚠️  Activation response: {r.stdout[:200]}")

print("\nDone! Workflow now processes up to 10 emails per 5-minute run.")
print("Simplified to fewer nodes — classify + apply labels in one Code node.")
