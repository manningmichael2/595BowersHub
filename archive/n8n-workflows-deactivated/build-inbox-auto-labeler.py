"""
Build the 'Inbox Auto-Labeler' workflow.

Watches INBOX for new unread emails. For each email:
  1. Extract subject, sender, and first ~1000 chars of body text
  2. Send to Haiku for classification: is this a receipt/order confirmation?
  3. If yes → process it directly (same logic as Email Receipts Importer):
     - Save attachments via Process Asset (vision)
     - Extract body receipt via Haiku text extraction
     - Create transactions for anything with a usable total
  4. Mark as seen so we don't re-scan

Design notes:
  - Cannot use IMAP COPY (community node not vetted for install).
    Instead, directly invokes the receipt processing pipeline.
  - Only processes UNSEEN messages to avoid re-scanning.
  - Haiku classification is cheap (~$0.001 per email) and fast (~0.5s).
  - Low-confidence classifications are skipped (lean toward false negatives).
  - The Email Receipts Importer (AI-Tags/Receipts label) remains as a
    manual fallback for emails the auto-labeler misses.

Triggered by:
  - IMAP poll on INBOX (unseen only, every 5 minutes)
"""
import json
import subprocess

from _config import API_KEY, N8N_URL

IMAP_CRED_ID = "ISns0rRRRmIETF2F"          # Gmail IMAP (App Password)
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"     # Anthropic API (httpHeaderAuth)
PROCESS_ASSET_WF_ID = "DeoZgLJCawzgcthm"
RECEIPT_TO_TX_WF_ID = "VGsnOuIM9aLiIxSw"
FILEWRITER_URL = "http://100.106.180.101:5001"

# ============================================================
# Code: Extract classification context from each email
# ============================================================
extract_context_code = r"""const out = [];
for (const item of $input.all()) {
  const msg = item.json;
  const subj = msg.subject || "";
  const from = (msg.from && (msg.from.value?.[0]?.address || msg.from.text)) || "";
  const messageId = msg.messageId || msg.uid || msg.headers?.["message-id"] || "";
  const uid = msg.uid;

  // Get body text (strip HTML)
  const html = msg.html || msg.textAsHtml || "";
  const text = msg.text || "";
  const stripped = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  const bodyPreview = (stripped || text).slice(0, 1000);

  // Check attachments
  const bin = item.binary || {};
  const attachmentNames = Object.keys(bin)
    .map(k => bin[k].fileName || bin[k].mimeType || 'unknown')
    .filter(n => n);

  out.push({
    json: {
      message_id: messageId,
      uid: uid,
      subject: subj,
      from_address: from,
      body_preview: bodyPreview,
      body_html: html,
      body_text: stripped || text,
      has_attachments: attachmentNames.length > 0,
      attachment_names: attachmentNames.join(', '),
    },
    // Pass binary through for attachment processing later
    binary: item.binary || {},
  });
}
return out;
"""

# ============================================================
# Code: Build Haiku classification prompt
# ============================================================
build_classify_prompt_code = r"""const ctx = $input.first().json;

const prompt = `Classify this email. Is it a purchase receipt, order confirmation, payment notification, or invoice?

Subject: ${ctx.subject}
From: ${ctx.from_address}
Has attachments: ${ctx.has_attachments}${ctx.attachment_names ? ' (' + ctx.attachment_names + ')' : ''}
Body preview:
---
${ctx.body_preview.slice(0, 800)}
---

Respond with ONLY a JSON object:
{
  "is_receipt": true/false,
  "confidence": "high"/"medium"/"low",
  "reason": "one sentence explanation"
}

Rules:
- "is_receipt" = true for: purchase receipts, order confirmations with totals, payment confirmations, invoices, subscription charges, e-receipts
- "is_receipt" = false for: shipping notifications without totals, marketing emails, newsletters, account alerts, password resets, social notifications, promotional offers, delivery updates without charges
- When in doubt, lean toward false (we'd rather miss a receipt than create false transactions)`;

const payload = {
  model: "claude-haiku-4-5-20251001",
  max_tokens: 256,
  messages: [{ role: "user", content: prompt }]
};

return [{
  json: {
    ...ctx,
    classify_payload: payload,
  }
}];
"""

# ============================================================
# Code: Parse Haiku classification response
# ============================================================
parse_classify_code = r"""const ctx = $('Build Classify Prompt').first().json;
const resp = $json;
let text = "";
try { text = (resp.content && resp.content[0] && resp.content[0].text) || ""; }
catch (e) { /* fall through */ }

text = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();

let classification = { is_receipt: false, confidence: "low", reason: "parse error" };
try {
  classification = JSON.parse(text);
} catch (e) {
  classification = { is_receipt: false, confidence: "low", reason: `parse error: ${text.slice(0, 100)}` };
}

// Only process as receipt if confidence is high or medium
const shouldProcess = classification.is_receipt === true
  && (classification.confidence === "high" || classification.confidence === "medium");

return [{
  json: {
    ...ctx,
    is_receipt: !!classification.is_receipt,
    confidence: classification.confidence || "unknown",
    reason: classification.reason || "",
    should_process: shouldProcess,
  }
}];
"""

# ============================================================
# IF: should we process this as a receipt?
# ============================================================
if_should_process = {
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
            "id": "should-process",
            "leftValue": "={{$json.should_process}}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }],
        "combinator": "and",
    },
}

# ============================================================
# Code: Fan out attachments (same as Email Receipts Importer)
# ============================================================
fan_out_attachments_code = r"""// From the classified email, fan out image/PDF attachments for processing.
const item = $input.first();
const ctx = item.json;
const bin = item.binary || {};
const out = [];

let attachIndex = 0;
for (const key of Object.keys(bin)) {
  const att = bin[key];
  const mime = att.mimeType || "application/octet-stream";
  if (!mime.startsWith("image/") && mime !== "application/pdf") continue;
  out.push({
    json: {
      message_id:    ctx.message_id,
      subject:       ctx.subject,
      from_address:  ctx.from_address,
      attachment_key: key,
      attachment_filename: att.fileName || `attachment-${attachIndex}`,
      attachment_mime: mime,
    },
    binary: { [key]: att, current: att },
  });
  attachIndex++;
}

// If no usable attachments, emit nothing
return out;
"""

# ============================================================
# Code: Prep attachment for inbox write
# ============================================================
prep_attachment_code = r"""const item = $input.first();
const ctx = item.json;
const binKey = ctx.attachment_key;

const bin = item.binary?.[binKey];
if (!bin) throw new Error(`Missing binary for key ${binKey}`);

const buffer = await this.helpers.getBinaryDataBuffer(0, binKey);
const b64 = buffer.toString('base64');

const safeName = (ctx.attachment_filename || 'attachment').replace(/[^A-Za-z0-9._-]/g, '_');
const idHash = (ctx.message_id || String(Date.now())).replace(/[^A-Za-z0-9]/g, '').slice(0, 16);
const inboxName = `autolabel-${idHash}-${safeName}`;
const inboxPath = `/files/inbox/${inboxName}`;

return [{
  json: {
    ...ctx,
    inbox_full_path: inboxPath,
    inbox_rel_path:  `inbox/${inboxName}`,
    base64:          b64,
    write_payload:   { path: inboxPath, base64: b64, overwrite: true },
    process_payload: {
      path:          `inbox/${inboxName}`,
      domain_hint:   "receipt",
      uploaded_by:   `email:${ctx.from_address || 'unknown'}`,
      original_name: ctx.attachment_filename,
    }
  }
}];
"""

# ============================================================
# Code: Decide whether to create transaction from Process Asset result
# ============================================================
decide_attach_tx_code = r"""const ctx = $('Prep Attachment').first().json;
const procRes = $json;

const hasUsableExtraction = procRes.ok
  && procRes.domain === 'receipt'
  && procRes.ai_extracted
  && typeof procRes.ai_extracted.total === 'number';

return [{
  json: {
    ...ctx,
    asset_id:     procRes.asset_id,
    skip_to_tx:   !hasUsableExtraction,
    tx_payload:   hasUsableExtraction
      ? { asset_id: procRes.asset_id, uploaded_by: `email:${ctx.from_address || 'unknown'}` }
      : null,
  }
}];
"""

# ============================================================
# Code: Process body as receipt (same logic as importer Path B)
# ============================================================
prep_body_code = r"""const ctx = $('Parse Classification').first().json;

// Skip if body is too short
if ((ctx.body_text || "").length < 200) {
  return [{ json: { ...ctx, skip_body: true, reason_skip: "body too short" } }];
}

const idHash = (ctx.message_id || String(Date.now()))
  .replace(/[^A-Za-z0-9]/g, '')
  .slice(0, 24) || `t${Date.now()}`;
const inboxName = `autolabel-body-${idHash}.html`;
const inboxPath = `/files/inbox/${inboxName}`;

const content = ctx.body_html || ctx.body_text;
const b64 = Buffer.from(content, 'utf-8').toString('base64');

return [{
  json: {
    ...ctx,
    skip_body: false,
    inbox_full_path: inboxPath,
    inbox_rel_path:  `inbox/${inboxName}`,
    original_name:   `${ctx.subject || 'email-receipt'}.html`,
    base64:          b64,
    mime:            'text/html',
    size_bytes:      Buffer.byteLength(content, 'utf-8'),
    write_payload:   { path: inboxPath, base64: b64, overwrite: true },
    probe_payload:   { path: inboxPath },
  }
}];
"""

# ============================================================
# Code: Parse body probe and build extraction prompt
# ============================================================
parse_body_and_prompt_code = r"""const ctx = $('Prep Body').first().json;
const probe = $json;
if (!probe.ok || !probe.exists) {
  throw new Error(`Body file not found: ${ctx.inbox_full_path}`);
}

// Truncate body for prompt
const bodyForPrompt = (ctx.body_text || "").slice(0, 8000);

const extractPrompt = `You are extracting receipt/purchase information from an email body.
The email subject was: "${ctx.subject || 'unknown'}"
The sender was: ${ctx.from_address || 'unknown'}

Here is the email body text:
---
${bodyForPrompt}
---

Return ONLY a JSON object with these keys:
- merchant (string|null): the store/service name
- total (number|null): the total amount charged (as a positive number, e.g. 17.49)
- currency (string|null): e.g. "USD"
- date (string|null): purchase date in YYYY-MM-DD format
- payment_method (string|null): e.g. "Visa ending 1234"
- line_items (array|null): array of {description, qty, price} if visible
- notes (string|null): any other relevant info (order number, shipping, etc.)

If this email does NOT appear to be a purchase receipt or order confirmation, return:
{"merchant": null, "total": null, "not_a_receipt": true}

Return the JSON object and nothing else.`;

const payload = {
  model: "claude-haiku-4-5-20251001",
  max_tokens: 1024,
  messages: [{ role: "user", content: extractPrompt }]
};

return [{
  json: {
    ...ctx,
    sha256:          probe.sha256,
    size_bytes:      probe.size_bytes || ctx.size_bytes,
    haiku_payload:   payload,
  }
}];
"""

# ============================================================
# Code: Parse body extraction and insert asset + maybe transaction
# ============================================================
parse_body_extract_code = r"""const ctx = $('Parse Body and Prompt').first().json;
const resp = $json;
let text = "";
try { text = (resp.content && resp.content[0] && resp.content[0].text) || ""; }
catch (e) { /* fall through */ }

text = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();

let extracted = null;
let isReceipt = false;
try {
  extracted = JSON.parse(text);
  if (extracted.not_a_receipt) {
    isReceipt = false;
  } else if (extracted.merchant && typeof extracted.total === 'number') {
    isReceipt = true;
  }
} catch (e) {
  extracted = { _raw: text, _parse_error: String(e) };
}

const summary = isReceipt
  ? `${extracted.merchant} - ${extracted.total}`
  : (extracted?.merchant || text.slice(0, 80));

return [{
  json: {
    ...ctx,
    ai_summary:   summary,
    ai_extracted: extracted,
    ai_model:     "claude-haiku-4-5-20251001",
    is_receipt:   isReceipt,
    has_total:    isReceipt && typeof extracted?.total === 'number',
  }
}];
"""

# Postgres: Insert body asset
body_insert_query = (
    "INSERT INTO files.assets (path, original_name, mime, size_bytes, sha256, domain, uploaded_by, "
    "ai_summary, ai_extracted, ai_model, processed_at) "
    "VALUES ("
    "  '{{$json.inbox_full_path}}', "
    "  '{{($json.original_name || '').replace(/'/g, \"''\")}}', "
    "  '{{$json.mime}}', "
    "  {{$json.size_bytes}}, "
    "  '{{$json.sha256}}', "
    "  'receipt', "
    "  'email:{{($json.from_address || '').replace(/'/g, \"''\")}}', "
    "  '{{($json.ai_summary || '').replace(/'/g, \"''\")}}', "
    "  '{{JSON.stringify($json.ai_extracted || {}).replace(/'/g, \"''\")}}'::jsonb, "
    "  '{{$json.ai_model}}', "
    "  now()"
    ") ON CONFLICT (sha256) DO NOTHING "
    "RETURNING id::text AS id"
)

# Code: After body insert, decide whether to create transaction
body_post_insert_code = r"""const ctx = $('Parse Body Extract').first().json;
const inserted = $input.first().json;
// ON CONFLICT DO NOTHING returns no rows if dedup hit
const assetId = inserted?.id || null;

return [{
  json: {
    ...ctx,
    asset_id: assetId,
    body_dedup: !assetId,
    should_create_tx: !!assetId && ctx.has_total,
    tx_payload: assetId && ctx.has_total
      ? { asset_id: assetId, uploaded_by: `email:${ctx.from_address || 'unknown'}` }
      : null,
  }
}];
"""

# ============================================================
# Code: Final summary
# ============================================================
summarize_skip_code = r"""const ctx = $json;
return [{
  json: {
    ok: true,
    action: "skipped",
    message_id: ctx.message_id,
    subject: ctx.subject,
    from: ctx.from_address,
    is_receipt: ctx.is_receipt,
    confidence: ctx.confidence,
    reason: ctx.reason,
  }
}];
"""

summarize_done_code = r"""const ctx = $json;
return [{
  json: {
    ok: true,
    action: "processed",
    message_id: ctx.message_id,
    subject: ctx.subject,
    from: ctx.from_address,
    confidence: ctx.confidence,
  }
}];
"""

# ============================================================
# Build workflow
# ============================================================
imap_creds = {"imap": {"id": IMAP_CRED_ID, "name": "Gmail IMAP (App Password)"}}
anthropic_creds = {"httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": "Anthropic API"}}
pg = {"postgres": {"id": "JvthRCvWKXaGGbBI", "name": "Finance Postgres"}}

workflow = {
    "name": "Inbox Auto-Labeler",
    "nodes": [
        # --- Trigger: INBOX, unseen only ---
        {
            "parameters": {
                "mailbox": "INBOX",
                "options": {},
                "format": "resolved",
                "downloadAttachments": True,
                "postProcessAction": "read",
            },
            "id": "n-imap",
            "name": "IMAP Trigger (Inbox)",
            "type": "n8n-nodes-base.emailReadImap",
            "typeVersion": 2,
            "position": [200, 500],
            "credentials": imap_creds,
        },

        # --- Classification ---
        {
            "parameters": {"jsCode": extract_context_code},
            "id": "n-extract",
            "name": "Extract Context",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 500],
        },
        {
            "parameters": {"jsCode": build_classify_prompt_code},
            "id": "n-classify-prompt",
            "name": "Build Classify Prompt",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [600, 500],
        },
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
                "jsonBody": "={{ JSON.stringify($json.classify_payload) }}",
                "options": {"timeout": 30000},
            },
            "id": "n-classify-call",
            "name": "Haiku Classify",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [800, 500],
            "credentials": anthropic_creds,
        },
        {
            "parameters": {"jsCode": parse_classify_code},
            "id": "n-parse-classify",
            "name": "Parse Classification",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1000, 500],
        },
        {
            "parameters": if_should_process,
            "id": "n-if-receipt",
            "name": "Is Receipt?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [1200, 500],
        },

        # --- NOT a receipt (top output) → summarize and done ---
        {
            "parameters": {"jsCode": summarize_skip_code},
            "id": "n-sum-skip",
            "name": "Summarize (skip)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1400, 350],
        },

        # --- IS a receipt (bottom output) → process body ---
        {
            "parameters": {"jsCode": prep_body_code},
            "id": "n-prep-body",
            "name": "Prep Body",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1400, 650],
        },
        {
            "parameters": {
                "method": "POST",
                "url": f"{FILEWRITER_URL}/write-base64",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($json.write_payload) }}",
                "options": {"timeout": 30000},
            },
            "id": "n-write-body",
            "name": "Write Body",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1600, 650],
        },
        {
            "parameters": {
                "method": "POST",
                "url": f"{FILEWRITER_URL}/probe",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($('Prep Body').first().json.probe_payload) }}",
                "options": {"timeout": 15000},
            },
            "id": "n-probe-body",
            "name": "Probe Body",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [1800, 650],
        },
        {
            "parameters": {"jsCode": parse_body_and_prompt_code},
            "id": "n-parse-body-prompt",
            "name": "Parse Body and Prompt",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2000, 650],
        },
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
                "options": {"timeout": 60000},
            },
            "id": "n-extract-body",
            "name": "Haiku Extract Body",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [2200, 650],
            "credentials": anthropic_creds,
        },
        {
            "parameters": {"jsCode": parse_body_extract_code},
            "id": "n-parse-extract",
            "name": "Parse Body Extract",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2400, 650],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": body_insert_query,
                "options": {},
            },
            "id": "n-insert-body",
            "name": "Insert Body Asset",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [2600, 650],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": body_post_insert_code},
            "id": "n-post-insert",
            "name": "Body Post Insert",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2800, 650],
        },
        # Call Receipt to Transaction if we have a total
        {
            "parameters": {
                "workflowId": {"__rl": True, "mode": "list", "value": RECEIPT_TO_TX_WF_ID},
                "workflowInputs": {
                    "value": "={{ $json.tx_payload }}",
                    "mappingMode": "passThrough",
                },
                "options": {},
            },
            "id": "n-body-tx",
            "name": "Receipt to Tx (body)",
            "type": "n8n-nodes-base.executeWorkflow",
            "typeVersion": 1.2,
            "position": [3000, 650],
            "executeOnce": False,
        },
        {
            "parameters": {"jsCode": summarize_done_code},
            "id": "n-sum-done",
            "name": "Summarize (done)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3200, 650],
        },
    ],
    "connections": {
        "IMAP Trigger (Inbox)":    {"main": [[{"node": "Extract Context",       "type": "main", "index": 0}]]},
        "Extract Context":         {"main": [[{"node": "Build Classify Prompt",  "type": "main", "index": 0}]]},
        "Build Classify Prompt":   {"main": [[{"node": "Haiku Classify",         "type": "main", "index": 0}]]},
        "Haiku Classify":          {"main": [[{"node": "Parse Classification",   "type": "main", "index": 0}]]},
        "Parse Classification":    {"main": [[{"node": "Is Receipt?",            "type": "main", "index": 0}]]},
        "Is Receipt?": {
            "main": [
                [{"node": "Summarize (skip)", "type": "main", "index": 0}],
                [{"node": "Prep Body",        "type": "main", "index": 0}],
            ]
        },
        "Prep Body":               {"main": [[{"node": "Write Body",             "type": "main", "index": 0}]]},
        "Write Body":              {"main": [[{"node": "Probe Body",             "type": "main", "index": 0}]]},
        "Probe Body":              {"main": [[{"node": "Parse Body and Prompt",  "type": "main", "index": 0}]]},
        "Parse Body and Prompt":   {"main": [[{"node": "Haiku Extract Body",     "type": "main", "index": 0}]]},
        "Haiku Extract Body":      {"main": [[{"node": "Parse Body Extract",     "type": "main", "index": 0}]]},
        "Parse Body Extract":      {"main": [[{"node": "Insert Body Asset",      "type": "main", "index": 0}]]},
        "Insert Body Asset":       {"main": [[{"node": "Body Post Insert",       "type": "main", "index": 0}]]},
        "Body Post Insert":        {"main": [[{"node": "Receipt to Tx (body)",   "type": "main", "index": 0}]]},
        "Receipt to Tx (body)":    {"main": [[{"node": "Summarize (done)",       "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}


# ============================================================
# Save and deploy
# ============================================================
with open('/home/michael/KiroProject/n8n-workflows/inbox-auto-labeler.json', 'w') as f:
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


def find_by_name(name):
    resp = api('GET', '/workflows?limit=250')
    for wf in resp.get('data', []):
        if wf.get('name') == name:
            return wf
    return None


payload = {k: workflow[k] for k in ('name', 'nodes', 'connections', 'settings')}
existing = find_by_name("Inbox Auto-Labeler")
if existing:
    wf_id = existing['id']
    print(f"Updating existing workflow: {wf_id}")
    if existing.get('active'):
        api('POST', f'/workflows/{wf_id}/deactivate')
    api('PUT', f'/workflows/{wf_id}', payload)
else:
    print("Creating new workflow")
    resp = api('POST', '/workflows', payload)
    wf_id = resp.get('id')

print(f"Workflow id: {wf_id}")
print()
print("Left INACTIVE — activate manually after reviewing.")
print()
print("What it does:")
print("  1. Watches INBOX for new unread emails")
print("  2. Classifies each with Haiku: is this a receipt?")
print("  3. If yes (high/medium confidence): extracts body, creates asset + transaction")
print("  4. Marks email as read regardless")
print()
print("Cost: ~$0.001 per email (Haiku classification)")
print("      + ~$0.001 per receipt (Haiku extraction)")
print()
print("NOTE: This processes receipts directly — no IMAP COPY to AI-Tags/Receipts.")
print("The AI-Tags/Receipts label + Email Receipts Importer remains as a manual fallback.")
