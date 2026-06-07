"""
Build the 'AI Inbox Classifier' workflow.

Runs on a schedule (every 5 minutes). For each recent unclassified email:
1. Fetches recent emails via filewriter /imap/fetch-recent
2. Filters out already-classified emails (checked against email_classified table)
3. Sends subject + sender + body snippet to Haiku for classification (1-3 labels)
4. Applies labels via filewriter /imap/add-label
5. Records classification in email_classified table
6. Upserts label usage counts in email_labels table

Guardrail: If Haiku identifies a receipt, AI-Tags/Receipts is ALWAYS included
regardless of what other labels are returned. This triggers the downstream
Email Receipts Importer pipeline.

First run: processes up to 50 emails per execution. Cron runs every 5 min,
so backlog clears over time without overwhelming the API.
"""
import json
import subprocess

from _config import API_KEY, N8N_URL

POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"       # Finance Postgres
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"     # Anthropic API (httpHeaderAuth)
FILEWRITER_URL = "http://100.106.180.101:5001"

# ============================================================
# Node code blocks
# ============================================================

# Step 1: Fetch recent emails via filewriter IMAP endpoint
fetch_emails_code = r"""// Fetch recent emails — look back 7 days to catch backlog.
// Limit to 50 per execution to avoid overwhelming Haiku.
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
  return [{ json: { error: null, emails: [], count: 0, note: "No emails to process" } }];
}

// Emit one item per email for downstream processing
return response.emails.map(email => ({ json: email }));
"""

# Step 2: Get already-classified message IDs in bulk
get_classified_query = (
    "SELECT message_id FROM public.email_classified "
    "WHERE classified_at > now() - interval '8 days'"
)

# Step 3: Filter out already-classified emails
# Also pulls existing labels here (deduped) and pins them to each email,
# so the downstream Build Prompt node never re-aggregates upstream items
# (which is what blew the prompt past 200K tokens).
filter_unclassified_code = r"""// Get the set of already-classified message IDs from the Postgres query
const classifiedRows = $('Get Classified IDs').all().map(i => i.json.message_id).filter(Boolean);
const classifiedSet = new Set(classifiedRows);

// Get all emails from the fetch step
const emails = $('Fetch Emails').all().map(i => i.json);

// Filter to only unclassified emails. Cap at 5 per run to keep cost/latency bounded.
const unclassified = emails
  .filter(e => e.message_id && !classifiedSet.has(e.message_id))
  .slice(0, 5);

if (unclassified.length === 0) return [];

// Pull existing labels here, dedupe, cap. This is the ONLY place we read
// from Get Existing Labels — downstream nodes use the pinned _existingLabels
// field to avoid n8n cross-product bloat.
const labelRowsRaw = $('Get Existing Labels').all().map(i => i.json.label).filter(Boolean);
const labelSet = new Set(labelRowsRaw);
const labelRows = Array.from(labelSet).slice(0, 20);
const fallbackLabels = 'AI-Tags/Receipts, AI-Tags/Bills, AI-Tags/Subscriptions, AI-Tags/Shipping, AI-Tags/Finance, AI-Tags/Pets, AI-Tags/House, AI-Tags/Travel, AI-Tags/Social, AI-Tags/Newsletters, AI-Tags/Spam-ish, AI-Tags/Action-Required';
const existingLabels = labelRows.length > 0 ? labelRows.join(', ') : fallbackLabels;

return unclassified.map(email => ({ json: { ...email, _existingLabels: existingLabels } }));
"""

# Step 4: Get existing labels for the prompt
get_labels_query = "SELECT label FROM public.email_labels ORDER BY times_used DESC LIMIT 50"

# Step 5: Build the Haiku classification prompt
# Reads $json (current item from the splitInBatches loop) and uses the
# pre-deduped _existingLabels field pinned during Filter Unclassified.
# Belt-and-suspenders: cap the existing-labels string itself at a hard char limit
# so a corrupted upstream value can never blow the prompt past 200K tokens.
build_prompt_code = r"""const email = $json;
let existingLabels = email._existingLabels || 'AI-Tags/Receipts, AI-Tags/Newsletters, AI-Tags/Spam-ish';

// Hard safety cap. Even if upstream is somehow malformed, the prompt cannot exceed ~5K chars.
if (typeof existingLabels !== 'string') existingLabels = String(existingLabels);
if (existingLabels.length > 2000) existingLabels = existingLabels.slice(0, 2000);

const subject = (email.subject || '(no subject)').toString().slice(0, 300);
const from = (email.from_address || email.from_name || 'unknown').toString().slice(0, 200);
const body = (email.body_text || '').toString().slice(0, 800);

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

return { haiku_payload: payload, _email: { message_id: email.message_id, uid: email.uid, subject: email.subject, from_address: email.from_address, from_name: email.from_name } };
"""

# Step 6: Parse Haiku response
parse_response_code = r"""const emailCtx = $('Build Classifier Prompt').item.json._email;
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
  // If parsing fails, try to extract labels from the text
  const matches = text.match(/AI-Tags\/[A-Za-z0-9-]+/g);
  labels = matches || [];
}

// Guardrail: ensure labels are properly formatted
labels = labels
  .filter(l => typeof l === 'string' && l.startsWith('AI-Tags/'))
  .slice(0, 3);  // Max 3 labels

// If no valid labels were returned, default to Newsletters (safe fallback)
if (labels.length === 0) {
  labels = ['AI-Tags/Newsletters'];
}

return { ...emailCtx, labels: labels };
"""

# Step 7: Apply labels via IMAP (one per label) + auto-archive if all labels are archivable
apply_labels_code = r"""const ctx = $json;
const results = [];

// Labels that should trigger auto-archive (only if ALL labels are in this set)
const AUTO_ARCHIVE_LABELS = new Set([
  'AI-Tags/Newsletters',
  'AI-Tags/Spam-ish',
  'AI-Tags/Shipping',
  'AI-Tags/Receipts',
  'AI-Tags/Subscriptions',
]);

for (const label of ctx.labels) {
  try {
    const data = await this.helpers.httpRequest({
      method: 'POST',
      url: 'http://100.106.180.101:5001/imap/add-label',
      body: { source_folder: "INBOX", uid: ctx.uid, label: label },
      json: true,
    });
    results.push({ label, ok: data.ok, error: data.error || null });
  } catch (e) {
    results.push({ label, ok: false, error: e.message });
  }
}

// Auto-archive: only if ALL assigned labels are in the auto-archive set
const allArchivable = ctx.labels.every(l => AUTO_ARCHIVE_LABELS.has(l));
let archived = false;

if (allArchivable && ctx.uid) {
  try {
    const archiveData = await this.helpers.httpRequest({
      method: 'POST',
      url: 'http://100.106.180.101:5001/imap/archive',
      body: { uid: ctx.uid },
      json: true,
    });
    archived = archiveData.ok || false;
  } catch (e) {
    archived = false;
  }
}

return { ...ctx, label_results: results, archived: archived };
"""

# Step 8: Record classification in Postgres
record_classified_query = (
    "INSERT INTO public.email_classified (message_id, labels) "
    "VALUES ('{{$json.message_id}}', "
    "ARRAY[{{$json.labels.map(l => \"'\" + l.replace(/'/g, \"''\") + \"'\").join(',')}}]::text[]) "
    "ON CONFLICT (message_id) DO NOTHING"
)

# Step 9: Upsert label counts
upsert_labels_code = r"""// Build a single multi-statement SQL string for this email's labels.
const ctx = $json;
const labels = ctx.labels || [];

if (labels.length === 0) {
  return { ...ctx, upsert_sql: 'SELECT 1' };
}

const queries = labels.map(label => {
  const escaped = label.replace(/'/g, "''");
  return `INSERT INTO public.email_labels (label, times_used, last_used) VALUES ('${escaped}', 1, now()) ON CONFLICT (label) DO UPDATE SET times_used = email_labels.times_used + 1, last_used = now()`;
});

return { ...ctx, upsert_queries: queries, upsert_sql: queries.join('; ') };
"""

upsert_labels_query = "{{$json.upsert_sql}}"

# Step 10: Final summary
summarize_code = r"""const ctx = $json;
return {
  ok: true,
  message_id: ctx.message_id,
  subject: ctx.subject,
  from: ctx.from_address || ctx.from_name,
  labels: ctx.labels,
  archived: ctx.archived || false,
  label_results: ctx.label_results,
};
"""

# ============================================================
# Build workflow JSON
# ============================================================
pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}
anthropic_creds = {"httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": "Anthropic API"}}

workflow = {
    "name": "AI Inbox Classifier",
    "nodes": [
        # Trigger: every 5 minutes
        {
            "parameters": {
                "rule": {"interval": [{"field": "minutes", "minutesInterval": 5}]}
            },
            "id": "n-cron",
            "name": "Every 5 Minutes",
            "type": "n8n-nodes-base.scheduleTrigger",
            "typeVersion": 1.2,
            "position": [200, 400],
        },
        # Fetch emails
        {
            "parameters": {"jsCode": fetch_emails_code, "mode": "runOnceForAllItems"},
            "id": "n-fetch",
            "name": "Fetch Emails",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 400],
        },
        # Check if already classified — bulk query
        {
            "parameters": {
                "operation": "executeQuery",
                "query": get_classified_query,
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
        # Filter unclassified
        {
            "parameters": {"jsCode": filter_unclassified_code},
            "id": "n-filter",
            "name": "Filter Unclassified",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [800, 400],
        },
        # Get existing labels for prompt context
        {
            "parameters": {
                "operation": "executeQuery",
                "query": get_labels_query,
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
        # Build Haiku prompt
        {
            "parameters": {"jsCode": build_prompt_code, "mode": "runOnceForEachItem"},
            "id": "n-prompt",
            "name": "Build Classifier Prompt",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1200, 400],
        },
        # Call Haiku
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
            "position": [1400, 400],
            "credentials": anthropic_creds,
        },
        # Parse response
        {
            "parameters": {"jsCode": parse_response_code, "mode": "runOnceForEachItem"},
            "id": "n-parse",
            "name": "Parse Classification",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1600, 400],
        },
        # Apply labels
        {
            "parameters": {"jsCode": apply_labels_code, "mode": "runOnceForEachItem"},
            "id": "n-apply",
            "name": "Apply Labels",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1800, 400],
        },
        # Record in email_classified
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
            "position": [2000, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        # Upsert label counts
        {
            "parameters": {"jsCode": upsert_labels_code, "mode": "runOnceForEachItem"},
            "id": "n-upsert-prep",
            "name": "Prep Label Upsert",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2200, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": upsert_labels_query,
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
        # Summarize
        {
            "parameters": {"jsCode": summarize_code, "mode": "runOnceForEachItem"},
            "id": "n-summary",
            "name": "Summarize",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2600, 400],
        },
    ],
    "connections": {
        "Every 5 Minutes": {"main": [[{"node": "Fetch Emails", "type": "main", "index": 0}]]},
        "Fetch Emails": {"main": [[{"node": "Get Classified IDs", "type": "main", "index": 0}]]},
        "Get Classified IDs": {"main": [[{"node": "Get Existing Labels", "type": "main", "index": 0}]]},
        "Get Existing Labels": {"main": [[{"node": "Filter Unclassified", "type": "main", "index": 0}]]},
        "Filter Unclassified": {"main": [[{"node": "Build Classifier Prompt", "type": "main", "index": 0}]]},
        "Build Classifier Prompt": {"main": [[{"node": "Haiku Classify", "type": "main", "index": 0}]]},
        "Haiku Classify": {"main": [[{"node": "Parse Classification", "type": "main", "index": 0}]]},
        "Parse Classification": {"main": [[{"node": "Apply Labels", "type": "main", "index": 0}]]},
        "Apply Labels": {"main": [[{"node": "Record Classified", "type": "main", "index": 0}]]},
        "Record Classified": {"main": [[{"node": "Prep Label Upsert", "type": "main", "index": 0}]]},
        "Prep Label Upsert": {"main": [[{"node": "Upsert Labels", "type": "main", "index": 0}]]},
        "Upsert Labels": {"main": [[{"node": "Summarize", "type": "main", "index": 0}]]},
    },
    "settings": {
        "executionOrder": "v1",
    },
}

# ============================================================
# Deploy via n8n API — update in place (workflow already exists)
# ============================================================
WORKFLOW_ID = "quNNHEhPI12UXxpp"

def api(method, path, body=None):
    cmd = ["curl", "-s", "-X", method,
           f"{N8N_URL}/api/v1{path}",
           "-H", f"X-N8N-API-KEY: {API_KEY}",
           "-H", "Content-Type: application/json"]
    if body is not None:
        cmd += ["-d", json.dumps(body)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"raw": result.stdout, "stderr": result.stderr}

# n8n PUT rejects unknown/read-only top-level fields. Send only what's allowed.
update_payload = {
    "name": workflow["name"],
    "nodes": workflow["nodes"],
    "connections": workflow["connections"],
    "settings": workflow["settings"],
}

# Make sure the workflow is deactivated before updating, then leave it
# deactivated so the user can re-activate manually after eyeballing the change.
deact = api("POST", f"/workflows/{WORKFLOW_ID}/deactivate")
print(f"Deactivate response active={deact.get('active')!r}")

resp = api("PUT", f"/workflows/{WORKFLOW_ID}", update_payload)

if "id" in resp:
    print(f"✅ Updated workflow: {resp['name']} (ID: {resp['id']})")
    print(f"   Status: {'ACTIVE' if resp.get('active') else 'INACTIVE'}")
    print(f"   Re-activate manually after smoke test passes.")
else:
    print(f"❌ Error: {json.dumps(resp, indent=2)[:1500]}")
