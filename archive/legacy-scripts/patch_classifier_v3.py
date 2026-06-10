import os
"""
Rebuild AI Inbox Classifier v3 — uses Split In Batches (Loop) pattern.

The issue: Code nodes can't use httpRequestWithAuthentication, and HTTP Request
nodes lose input context. Solution: use Split In Batches to process one item at
a time through the HTTP Request node, with a Code node before and after that
preserves context by embedding email data in the request/response.

Flow:
  Cron → Fetch → Get Classified IDs → Filter (max 10) → Get Labels
       → Loop Over Items (batch size 1)
           → Build Prompt (embeds email context in metadata field)
           → HTTP Request (Haiku) 
           → Parse + Apply Labels (single code node: parses response, applies labels, archives)
           → Record Classified (Postgres)
           → Upsert Labels (Postgres)
       → [loop back]
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
# Code blocks
# ============================================================

fetch_emails_code = r"""const response = await this.helpers.httpRequest({
  method: 'POST',
  url: 'http://100.106.180.101:5001/imap/fetch-recent',
  body: { folder: "INBOX", since_minutes: 10080, limit: 50, include_body: true, body_max_chars: 2000 },
  json: true,
});

if (!response || !response.ok || !response.emails || response.emails.length === 0) {
  return [];
}

return response.emails.map(email => ({ json: email }));
"""

filter_unclassified_code = r"""const classifiedRows = $('Get Classified IDs').all().map(i => i.json.message_id).filter(Boolean);
const classifiedSet = new Set(classifiedRows);
const emails = $('Fetch Emails').all().map(i => i.json);
const unclassified = emails.filter(e => e.message_id && !classifiedSet.has(e.message_id)).slice(0, 10);

if (unclassified.length === 0) return [];
return unclassified.map(email => ({ json: email }));
"""

build_prompt_code = r"""const email = $json;
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

// Store email context alongside the payload so we can retrieve it after HTTP Request
return [{ json: { haiku_payload: payload, _email: { message_id: email.message_id, uid: email.uid, subject: email.subject, from_address: email.from_address, from_name: email.from_name } } }];
"""

# After HTTP Request, parse response + apply labels + archive
parse_and_apply_code = r"""const resp = $json;  // This is the Haiku API response
const emailCtx = $('Build Prompt').item.json._email;  // Get email context from the input to HTTP Request

let text = "";
try { text = (resp.content && resp.content[0] && resp.content[0].text) || ""; }
catch (e) {}

text = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();

let labels = [];
try {
  const parsed = JSON.parse(text);
  labels = Array.isArray(parsed.labels) ? parsed.labels : [];
} catch (e) {
  const matches = text.match(/AI-Tags\/[A-Za-z0-9-]+/g);
  labels = matches || [];
}

labels = labels.filter(l => typeof l === 'string' && l.startsWith('AI-Tags/')).slice(0, 3);
if (labels.length === 0) labels = ['AI-Tags/Newsletters'];

// Apply labels via IMAP
const AUTO_ARCHIVE_LABELS = new Set([
  'AI-Tags/Newsletters', 'AI-Tags/Spam-ish', 'AI-Tags/Shipping',
  'AI-Tags/Receipts', 'AI-Tags/Subscriptions',
]);

for (const label of labels) {
  try {
    await this.helpers.httpRequest({
      method: 'POST',
      url: 'http://100.106.180.101:5001/imap/add-label',
      body: { source_folder: "INBOX", uid: emailCtx.uid, label: label },
      json: true,
    });
  } catch (e) {}
}

// Auto-archive if all labels are archivable
let archived = false;
if (labels.every(l => AUTO_ARCHIVE_LABELS.has(l)) && emailCtx.uid) {
  try {
    const r = await this.helpers.httpRequest({
      method: 'POST',
      url: 'http://100.106.180.101:5001/imap/archive',
      body: { uid: emailCtx.uid },
      json: true,
    });
    archived = r.ok || false;
  } catch (e) {}
}

return [{ json: {
  message_id: emailCtx.message_id,
  subject: emailCtx.subject,
  from: emailCtx.from_address || emailCtx.from_name,
  labels: labels,
  archived: archived,
}}];
"""

upsert_labels_code = r"""const labels = $json.labels || [];
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
        # Loop: process items one at a time through the Haiku call
        {
            "parameters": {"batchSize": 1, "options": {}},
            "id": "n-loop",
            "name": "Loop Over Items",
            "type": "n8n-nodes-base.splitInBatches",
            "typeVersion": 3,
            "position": [1200, 400],
        },
        # Build prompt per item
        {
            "parameters": {"jsCode": build_prompt_code},
            "id": "n-prompt",
            "name": "Build Prompt",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1400, 400],
        },
        # HTTP Request to Haiku
        {
            "parameters": {
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
                "jsonBody": "={{ JSON.stringify($json.haiku_payload) }}",
                "options": {"timeout": 30000},
            },
            "id": "n-haiku",
            "name": "Haiku Classify",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1600, 400],
            "credentials": anthropic_creds,
        },
        # Parse response + apply labels + archive
        {
            "parameters": {"jsCode": parse_and_apply_code},
            "id": "n-parse",
            "name": "Parse and Apply",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1800, 400],
        },
        # Record in DB
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "INSERT INTO public.email_classified (message_id, labels) VALUES ('{{$json.message_id}}', ARRAY[{{$json.labels.map(l => \"'\" + l.replace(/'/g, \"''\") + \"'\").join(',')}}]::text[]) ON CONFLICT (message_id) DO NOTHING",
                "options": {},
            },
            "id": "n-record",
            "name": "Record Classified",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [2000, 400],
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
            "position": [2200, 400],
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
            "position": [2400, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
    ],
    "connections": {
        "Every 5 Minutes": {"main": [[{"node": "Fetch Emails", "type": "main", "index": 0}]]},
        "Fetch Emails": {"main": [[{"node": "Get Classified IDs", "type": "main", "index": 0}]]},
        "Get Classified IDs": {"main": [[{"node": "Filter Unclassified", "type": "main", "index": 0}]]},
        "Filter Unclassified": {"main": [[{"node": "Get Existing Labels", "type": "main", "index": 0}]]},
        "Get Existing Labels": {"main": [[{"node": "Loop Over Items", "type": "main", "index": 0}]]},
        # Loop has 2 outputs: output 0 = "done" (all items processed), output 1 = "loop" (next item)
        "Loop Over Items": {"main": [
            [],  # output 0: done — nothing connected (end of workflow)
            [{"node": "Build Prompt", "type": "main", "index": 0}],  # output 1: next item
        ]},
        "Build Prompt": {"main": [[{"node": "Haiku Classify", "type": "main", "index": 0}]]},
        "Haiku Classify": {"main": [[{"node": "Parse and Apply", "type": "main", "index": 0}]]},
        "Parse and Apply": {"main": [[{"node": "Record Classified", "type": "main", "index": 0}]]},
        "Record Classified": {"main": [[{"node": "Prep Label Upsert", "type": "main", "index": 0}]]},
        "Prep Label Upsert": {"main": [[{"node": "Upsert Labels", "type": "main", "index": 0}]]},
        # Loop back to Loop Over Items for the next batch
        "Upsert Labels": {"main": [[{"node": "Loop Over Items", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}

# ============================================================
# Deploy
# ============================================================
# Deactivate first
subprocess.run(
    ["curl", "-s", "-X", "POST",
     f"{N8N_URL}/api/v1/workflows/{WORKFLOW_ID}/deactivate",
     "-H", f"X-N8N-API-KEY: {API_KEY}"],
    capture_output=True, text=True
)

update_payload = {
    "nodes": workflow["nodes"],
    "connections": workflow["connections"],
    "settings": workflow["settings"],
    "name": workflow["name"],
}

print("Updating workflow (v3 — Split In Batches loop)...")
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

print("Activating...")
r = subprocess.run(
    ["curl", "-s", "-X", "POST",
     f"{N8N_URL}/api/v1/workflows/{WORKFLOW_ID}/activate",
     "-H", f"X-N8N-API-KEY: {API_KEY}"],
    capture_output=True, text=True
)
resp = json.loads(r.stdout) if r.stdout else {}
print(f"  Active: {resp.get('active')}")
print("\nDone! Uses Split In Batches to loop through up to 10 emails per run.")
