"""
Build the 'Email Receipts Importer' workflow (v2 — body receipt support).

Watches the Gmail label 'Receipts' for new messages. For each message:

  PATH A — Attachments (unchanged from v1):
    1. Iterate attachments (images, PDFs)
    2. Save each to /files/inbox/ via filewriter
    3. Call Process Asset (domain_hint=receipt)
    4. If domain came back as 'receipt' with a parseable total, call
       Receipt to Transaction

  PATH B — Body Receipt (NEW):
    1. Check if the email body has substantial text (>200 chars stripped)
    2. Save the HTML body as a .html file to /files/inbox/
    3. Insert a files.assets row directly (no vision — it's text)
    4. Send the body text to Haiku with the receipt extraction prompt
    5. Update the asset row with AI results
    6. If extraction has a usable total, call Receipt to Transaction

Both paths run for every email. An email with attachments AND a body receipt
will produce entries from both paths. Dedup in Receipt to Transaction
(ON CONFLICT DO NOTHING on transaction id) and Process Asset (sha256 dedup)
prevent duplicates if the same data appears in both.

User responsibilities:
  - Create a Gmail label 'Receipts' and optionally 'Receipts/Imported'
  - Apply 'Receipts' to messages you want imported

Triggered by:
  - IMAP poll on the Receipts folder
"""
import json
import subprocess

from _config import API_KEY, N8N_URL

IMAP_CRED_ID = "ISns0rRRRmIETF2F"          # Gmail IMAP (App Password)
POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"       # Finance Postgres
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"     # Anthropic API (httpHeaderAuth)
PROCESS_ASSET_WF_ID    = "DeoZgLJCawzgcthm"
RECEIPT_TO_TX_WF_ID    = "VGsnOuIM9aLiIxSw"

FILEWRITER_URL = "http://100.106.180.101:5001"


# ============================================================
# PATH A — Attachment processing (unchanged from v1)
# ============================================================

# Code: For each new email, emit one item per attachment.
fan_out_attachments_code = r"""// IMAP Trigger emits one item per email. Each email may have N attachments
// in `binary`. We need to fan out to one item per attachment so downstream
// runs once per file.
const out = [];
for (const item of $input.all()) {
  const msg = item.json;
  const bin = item.binary || {};
  const subj = msg.subject || "";
  const from = (msg.from && (msg.from.value?.[0]?.address || msg.from.text)) || "";
  const messageId = msg.messageId || msg.uid || msg.headers?.["message-id"] || "";

  let attachIndex = 0;
  for (const key of Object.keys(bin)) {
    const att = bin[key];
    const mime = att.mimeType || "application/octet-stream";
    // Only images and PDFs for now.
    if (!mime.startsWith("image/") && mime !== "application/pdf") continue;
    out.push({
      json: {
        message_id:    messageId,
        message_uid:   msg.uid,
        subject:       subj,
        from_address:  from,
        attachment_key: key,
        attachment_filename: att.fileName || `attachment-${attachIndex}`,
        attachment_mime: mime,
      },
      binary: { [key]: att, current: att },
    });
    attachIndex++;
  }
}
// If no usable attachments, emit nothing — downstream won't fire.
return out;
"""

# Code: Convert binary attachment to base64 + build inbox filename.
prep_inbox_payload_code = r"""const item = $input.first();
const ctx  = item.json;
const binKey = ctx.attachment_key;

const bin = item.binary?.[binKey];
if (!bin) throw new Error(`Missing binary for key ${binKey}`);

const buffer = await this.helpers.getBinaryDataBuffer(0, binKey);
const b64 = buffer.toString('base64');

const safeName = (ctx.attachment_filename || 'attachment').replace(/[^A-Za-z0-9._-]/g, '_');
const idHash = (ctx.message_id || String(Date.now())).replace(/[^A-Za-z0-9]/g, '').slice(0, 16);
const inboxName = `email-${idHash}-${safeName}`;
const inboxPath = `/files/inbox/${inboxName}`;

return [{
  json: {
    ...ctx,
    inbox_full_path: inboxPath,
    inbox_rel_path:  `inbox/${inboxName}`,
    base64:          b64,
    write_payload:   { path: inboxPath, base64: b64, overwrite: true },
  }
}];
"""

# Code: Build payload for Process Asset
build_process_payload_code = r"""const ctx = $('Prep Inbox Payload').first().json;
return [{
  json: {
    ...ctx,
    process_payload: {
      path:          ctx.inbox_rel_path,
      domain_hint:   "receipt",
      uploaded_by:   `email:${ctx.from_address || 'unknown'}`,
      original_name: ctx.attachment_filename,
    }
  }
}];
"""

# Code: Decide whether to call Receipt to Transaction.
decide_to_tx_code = r"""const ctx     = $('Build Process Payload').first().json;
const procRes = $json;

const hasUsableExtraction = procRes.ok
  && procRes.domain === 'receipt'
  && procRes.ai_extracted
  && typeof procRes.ai_extracted.total === 'number';

return [{
  json: {
    ...ctx,
    asset_id:     procRes.asset_id,
    proc_dedup:   !!procRes.dedup,
    proc_domain:  procRes.domain,
    skip_to_tx:   !hasUsableExtraction,
    tx_payload:   { asset_id: procRes.asset_id, uploaded_by: `email:${ctx.from_address || 'unknown'}` },
  }
}];
"""

if_skip_to_tx_conditions = {
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
            "id": "skip-tx",
            "leftValue": "={{$json.skip_to_tx}}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }],
        "combinator": "and",
    },
}

summarize_code = r"""const ctx = $json;
return [{
  json: {
    ok: true,
    path: "attachment",
    message_id:        ctx.message_id,
    subject:           ctx.subject,
    from:              ctx.from_address,
    attachment:        ctx.attachment_filename,
    asset_id:          ctx.asset_id,
    domain:            ctx.proc_domain,
    transaction_id:    ctx.transaction_id || null,
    transaction_skipped: ctx.transaction_skipped || null,
    note: ctx.skip_to_tx
      ? `attachment processed but no usable receipt data — left as asset only`
      : `imported as ${ctx.transaction_id} (skipped=${ctx.transaction_skipped})`,
  }
}];
"""

capture_tx_code = r"""const ctx = $('Decide to Tx').first().json;
const tx  = $json;
return [{
  json: {
    ...ctx,
    transaction_id:      tx.transaction_id,
    transaction_skipped: !!tx.skipped,
  }
}];
"""


# ============================================================
# PATH B — Body Receipt (NEW)
# ============================================================

# Code: Extract email body text. Emit one item if body looks substantial.
# Skip if body is too short (likely just a signature or "see attached").
extract_body_code = r"""// For each email, check if the body has enough text to be a receipt.
// IMAP gives us textAsHtml or html or text fields.
const out = [];
for (const item of $input.all()) {
  const msg = item.json;
  const subj = msg.subject || "";
  const from = (msg.from && (msg.from.value?.[0]?.address || msg.from.text)) || "";
  const messageId = msg.messageId || msg.uid || msg.headers?.["message-id"] || "";

  // Get the richest body available
  const html = msg.html || msg.textAsHtml || "";
  const text = msg.text || "";

  // Strip HTML tags for length check
  const stripped = html.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
  const bodyText = stripped || text;

  // Skip if body is too short to be a receipt (signatures, "see attached", etc.)
  if (bodyText.length < 200) continue;

  // Also skip if the body is just a generic "your order has shipped" with no amounts
  // We'll let Haiku decide — but at least filter out trivially short bodies.

  out.push({
    json: {
      message_id:    messageId,
      message_uid:   msg.uid,
      subject:       subj,
      from_address:  from,
      body_html:     html,
      body_text:     bodyText,
      body_length:   bodyText.length,
    }
  });
}
return out;
"""

# Code: Save body as HTML file and prepare for asset insertion.
# Note: n8n blocks require('crypto'), so we use filewriter's /probe to get sha256
# after writing the file (same pattern as Process Asset).
prep_body_asset_code = r"""const ctx = $input.first().json;

// Build a deterministic-ish filename from message_id (no crypto needed —
// this is just a filename, not a security boundary).
const idHash = (ctx.message_id || String(Date.now()))
  .replace(/[^A-Za-z0-9]/g, '')
  .slice(0, 24) || `t${Date.now()}`;
const inboxName = `email-body-${idHash}.html`;
const inboxPath = `/files/inbox/${inboxName}`;

// Base64-encode the HTML body for filewriter
const content = ctx.body_html || ctx.body_text;
const b64 = Buffer.from(content, 'utf-8').toString('base64');

return [{
  json: {
    ...ctx,
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

# Code: Merge probe response (sha256, mime, size) back into context
parse_body_probe_code = r"""const ctx = $('Prep Body Asset').first().json;
const probe = $json;
if (!probe.ok || !probe.exists) {
  throw new Error(`Body file not found after write: ${ctx.inbox_full_path} (${JSON.stringify(probe)})`);
}
return [{
  json: {
    ...ctx,
    sha256:     probe.sha256,
    // probe.mime will be text/html; trust the probe over our guess
    mime:       probe.mime || ctx.mime,
    size_bytes: probe.size_bytes || ctx.size_bytes,
  }
}];
"""

# Postgres: Check dedup by sha256 before inserting
body_dedup_query = (
    "SELECT id::text AS id FROM files.assets "
    "WHERE sha256 = '{{$json.sha256}}' LIMIT 1"
)

# Code: Branch on dedup — skip if already exists
body_dedup_branch_code = r"""const ctx = $('Parse Body Probe').first().json;
const rows = $input.all().map(i => i.json).filter(r => r && r.id);
if (rows.length > 0) {
  // Already processed this exact body content
  return [{ json: { ...ctx, dedup: true, asset_id: rows[0].id, skip_body: true } }];
}
return [{ json: { ...ctx, dedup: false, skip_body: false } }];
"""

if_body_dedup_conditions = {
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
            "id": "body-dedup",
            "leftValue": "={{$json.skip_body}}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }],
        "combinator": "and",
    },
}

# Postgres: Insert asset row for the body HTML
body_insert_query = (
    "INSERT INTO files.assets (path, original_name, mime, size_bytes, sha256, domain, uploaded_by) "
    "VALUES ("
    "  '{{$json.inbox_full_path}}', "
    "  '{{($json.original_name || '').replace(/'/g, \"''\")}}', "
    "  '{{$json.mime}}', "
    "  {{$json.size_bytes}}, "
    "  '{{$json.sha256}}', "
    "  'receipt', "
    "  'email:{{($json.from_address || '').replace(/'/g, \"''\")}}'"
    ") RETURNING id::text AS id"
)

# Code: Capture the new asset_id
body_post_insert_code = r"""const ctx = $('Body Dedup Branch').first().json;
const inserted = $input.first().json;
return [{ json: { ...ctx, asset_id: inserted.id } }];
"""


# Code: Build the Haiku text extraction prompt for the body
build_body_prompt_code = r"""const ctx = $('Body Post Insert').first().json;

// Truncate body to ~8000 chars to stay within reasonable token limits
const bodyForPrompt = (ctx.body_text || "").slice(0, 8000);

const prompt = `You are extracting receipt/purchase information from an email body.
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
  messages: [{
    role: "user",
    content: prompt
  }]
};

return [{
  json: {
    ...ctx,
    haiku_payload: payload,
  }
}];
"""

# Code: Parse Haiku response for body receipt
parse_body_haiku_code = r"""const ctx = $('Build Body Prompt').first().json;
const resp = $json;
let text = "";
try { text = (resp.content && resp.content[0] && resp.content[0].text) || ""; }
catch (e) { /* fall through */ }

text = text.trim().replace(/^```(?:json)?/, "").replace(/```$/, "").trim();

let extracted = null;
let summary   = null;
let isReceipt = false;

try {
  extracted = JSON.parse(text);
  if (extracted.not_a_receipt) {
    summary = "Not a receipt";
    isReceipt = false;
  } else if (extracted.merchant && typeof extracted.total === 'number') {
    summary = `${extracted.merchant} - ${extracted.total}`;
    isReceipt = true;
  } else if (extracted.merchant) {
    summary = extracted.merchant;
    isReceipt = false; // no total = can't create transaction
  } else {
    summary = text.slice(0, 120);
    isReceipt = false;
  }
} catch (e) {
  summary = text.slice(0, 200);
  extracted = { _raw: text, _parse_error: String(e) };
  isReceipt = false;
}

return [{
  json: {
    ...ctx,
    ai_summary:     summary,
    ai_extracted:   extracted,
    ai_model:       "claude-haiku-4-5-20251001",
    is_receipt:     isReceipt,
    has_total:      isReceipt && typeof extracted?.total === 'number',
  }
}];
"""

# Postgres: Update the asset row with AI extraction results
body_update_query = (
    "UPDATE files.assets SET "
    "  ai_summary   = '{{($json.ai_summary || '').replace(/'/g, \"''\")}}', "
    "  ai_extracted = '{{JSON.stringify($json.ai_extracted || {}).replace(/'/g, \"''\")}}'::jsonb, "
    "  ai_model     = '{{$json.ai_model}}', "
    "  processed_at = now() "
    "WHERE id = '{{$json.asset_id}}'::uuid"
)

# Code: Decide whether to create a transaction from body extraction
body_decide_tx_code = r"""const ctx = $json;
return [{
  json: {
    ...ctx,
    skip_body_tx: !ctx.has_total,
    tx_payload: ctx.has_total
      ? { asset_id: ctx.asset_id, uploaded_by: `email:${ctx.from_address || 'unknown'}` }
      : null,
  }
}];
"""

if_body_skip_tx_conditions = {
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
            "id": "body-skip-tx",
            "leftValue": "={{$json.skip_body_tx}}",
            "rightValue": True,
            "operator": {"type": "boolean", "operation": "true", "singleValue": True},
        }],
        "combinator": "and",
    },
}

# Code: Capture body tx result
body_capture_tx_code = r"""const ctx = $('Body Decide Tx').first().json;
const tx  = $json;
return [{
  json: {
    ...ctx,
    transaction_id:      tx.transaction_id,
    transaction_skipped: !!tx.skipped,
  }
}];
"""

# Code: Summarize body path result
body_summarize_code = r"""const ctx = $json;
return [{
  json: {
    ok: true,
    path: "body",
    message_id:        ctx.message_id,
    subject:           ctx.subject,
    from:              ctx.from_address,
    asset_id:          ctx.asset_id,
    is_receipt:        ctx.is_receipt,
    ai_summary:        ctx.ai_summary,
    transaction_id:    ctx.transaction_id || null,
    transaction_skipped: ctx.transaction_skipped || null,
    note: ctx.skip_body_tx
      ? (ctx.is_receipt ? 'body parsed as receipt but no total found' : 'body is not a receipt')
      : `body receipt imported as ${ctx.transaction_id || 'unknown'}`,
  }
}];
"""

# Summarize for dedup-skipped bodies
body_dedup_summarize_code = r"""const ctx = $json;
return [{
  json: {
    ok: true,
    path: "body",
    message_id:  ctx.message_id,
    subject:     ctx.subject,
    from:        ctx.from_address,
    asset_id:    ctx.asset_id,
    note:        "body already processed (sha256 dedup)",
    dedup:       true,
  }
}];
"""


# ============================================================
# Build workflow
# ============================================================
imap_creds = {"imap": {"id": IMAP_CRED_ID, "name": "Gmail IMAP (App Password)"}}
pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}
anthropic_creds = {"httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": "Anthropic API"}}

workflow = {
    "name": "Email Receipts Importer",
    "nodes": [
        # --- Trigger ---
        {
            "parameters": {
                "mailbox": "AI-Tags/Receipts",
                "options": {},
                "format": "resolved",
                "downloadAttachments": True,
                "postProcessAction": "read",
            },
            "id": "n-imap",
            "name": "IMAP Trigger (Receipts)",
            "type": "n8n-nodes-base.emailReadImap",
            "typeVersion": 2,
            "position": [200, 500],
            "credentials": imap_creds,
        },

        # ===== PATH A: Attachments (top row, y=300) =====
        {
            "parameters": {"jsCode": fan_out_attachments_code},
            "id": "n-fan",
            "name": "Fan Out Attachments",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [450, 300],
        },
        {
            "parameters": {"jsCode": prep_inbox_payload_code},
            "id": "n-prep",
            "name": "Prep Inbox Payload",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [650, 300],
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
            "id": "n-write",
            "name": "Write Attachment",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [850, 300],
        },
        {
            "parameters": {"jsCode": build_process_payload_code},
            "id": "n-bp",
            "name": "Build Process Payload",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1050, 300],
        },
        {
            "parameters": {
                "workflowId": {"__rl": True, "mode": "list", "value": PROCESS_ASSET_WF_ID},
                "workflowInputs": {
                    "value": "={{ $json.process_payload }}",
                    "mappingMode": "passThrough",
                },
                "options": {},
            },
            "id": "n-proc",
            "name": "Run Process Asset",
            "type": "n8n-nodes-base.executeWorkflow",
            "typeVersion": 1.2,
            "position": [1250, 300],
        },
        {
            "parameters": {"jsCode": decide_to_tx_code},
            "id": "n-decide",
            "name": "Decide to Tx",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1450, 300],
        },
        {
            "parameters": if_skip_to_tx_conditions,
            "id": "n-if-skip",
            "name": "Skip Tx?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [1650, 300],
        },
        {
            "parameters": {"jsCode": summarize_code},
            "id": "n-sum-skip",
            "name": "Summarize A (no tx)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1850, 160],
        },
        {
            "parameters": {
                "workflowId": {"__rl": True, "mode": "list", "value": RECEIPT_TO_TX_WF_ID},
                "workflowInputs": {
                    "value": "={{ $json.tx_payload }}",
                    "mappingMode": "passThrough",
                },
                "options": {},
            },
            "id": "n-tx",
            "name": "Attach Tx (A)",
            "type": "n8n-nodes-base.executeWorkflow",
            "typeVersion": 1.2,
            "position": [1850, 440],
        },
        {
            "parameters": {"jsCode": capture_tx_code},
            "id": "n-capture",
            "name": "Capture Tx (A)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2050, 440],
        },
        {
            "parameters": {"jsCode": summarize_code},
            "id": "n-sum-tx",
            "name": "Summarize A (tx)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2250, 440],
        },

        # ===== PATH B: Body Receipt (bottom row, y=700) =====
        {
            "parameters": {"jsCode": extract_body_code},
            "id": "n-body-extract",
            "name": "Extract Body",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [450, 700],
        },
        {
            "parameters": {"jsCode": prep_body_asset_code},
            "id": "n-body-prep",
            "name": "Prep Body Asset",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [650, 700],
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
            "id": "n-body-write",
            "name": "Write Body HTML",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [850, 700],
        },
        {
            "parameters": {
                "method": "POST",
                "url": f"{FILEWRITER_URL}/probe",
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify($('Prep Body Asset').first().json.probe_payload) }}",
                "options": {"timeout": 15000},
            },
            "id": "n-body-probe",
            "name": "Probe Body",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [950, 700],
        },
        {
            "parameters": {"jsCode": parse_body_probe_code},
            "id": "n-body-parse-probe",
            "name": "Parse Body Probe",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1050, 700],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": body_dedup_query,
                "options": {},
            },
            "id": "n-body-dedup",
            "name": "Body Dedup Query",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1050, 700],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": body_dedup_branch_code},
            "id": "n-body-dedup-branch",
            "name": "Body Dedup Branch",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1250, 700],
        },
        {
            "parameters": if_body_dedup_conditions,
            "id": "n-body-if-dedup",
            "name": "Body Dedup?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [1450, 700],
        },
        # Dedup=true branch (top output) → summarize and stop
        {
            "parameters": {"jsCode": body_dedup_summarize_code},
            "id": "n-body-dedup-sum",
            "name": "Summarize B (dedup)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1650, 580],
        },
        # Dedup=false branch (bottom output) → insert asset
        {
            "parameters": {
                "operation": "executeQuery",
                "query": body_insert_query,
                "options": {},
            },
            "id": "n-body-insert",
            "name": "Insert Body Asset",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1650, 820],
            "credentials": pg,
        },
        {
            "parameters": {"jsCode": body_post_insert_code},
            "id": "n-body-post-insert",
            "name": "Body Post Insert",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1850, 820],
        },
        {
            "parameters": {"jsCode": build_body_prompt_code},
            "id": "n-body-prompt",
            "name": "Build Body Prompt",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2050, 820],
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
            "id": "n-body-haiku",
            "name": "Haiku Extract Body",
            "type": "n8n-nodes-base.httpRequest",
            "typeVersion": 4.2,
            "position": [2250, 820],
            "credentials": anthropic_creds,
        },
        {
            "parameters": {"jsCode": parse_body_haiku_code},
            "id": "n-body-parse",
            "name": "Parse Body Haiku",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2450, 820],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": body_update_query,
                "options": {},
            },
            "id": "n-body-update",
            "name": "Update Body Asset",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [2650, 820],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": body_decide_tx_code},
            "id": "n-body-decide-tx",
            "name": "Body Decide Tx",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [2850, 820],
        },
        {
            "parameters": if_body_skip_tx_conditions,
            "id": "n-body-if-skip-tx",
            "name": "Body Skip Tx?",
            "type": "n8n-nodes-base.if",
            "typeVersion": 2,
            "position": [3050, 820],
        },
        # Skip tx (top output)
        {
            "parameters": {"jsCode": body_summarize_code},
            "id": "n-body-sum-skip",
            "name": "Summarize B (no tx)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3250, 700],
        },
        # Has tx (bottom output)
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
            "name": "Body Tx",
            "type": "n8n-nodes-base.executeWorkflow",
            "typeVersion": 1.2,
            "position": [3250, 940],
        },
        {
            "parameters": {"jsCode": body_capture_tx_code},
            "id": "n-body-capture-tx",
            "name": "Body Capture Tx",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3450, 940],
        },
        {
            "parameters": {"jsCode": body_summarize_code},
            "id": "n-body-sum-tx",
            "name": "Summarize B (tx)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [3650, 940],
        },
    ],
    "connections": {
        # Trigger fans out to both paths
        "IMAP Trigger (Receipts)": {"main": [[
            {"node": "Fan Out Attachments", "type": "main", "index": 0},
            {"node": "Extract Body",        "type": "main", "index": 0},
        ]]},

        # PATH A connections
        "Fan Out Attachments":      {"main": [[{"node": "Prep Inbox Payload",   "type": "main", "index": 0}]]},
        "Prep Inbox Payload":       {"main": [[{"node": "Write Attachment",     "type": "main", "index": 0}]]},
        "Write Attachment":         {"main": [[{"node": "Build Process Payload","type": "main", "index": 0}]]},
        "Build Process Payload":    {"main": [[{"node": "Run Process Asset",   "type": "main", "index": 0}]]},
        "Run Process Asset":        {"main": [[{"node": "Decide to Tx",        "type": "main", "index": 0}]]},
        "Decide to Tx":             {"main": [[{"node": "Skip Tx?",            "type": "main", "index": 0}]]},
        "Skip Tx?": {
            "main": [
                [{"node": "Summarize A (no tx)", "type": "main", "index": 0}],
                [{"node": "Attach Tx (A)",       "type": "main", "index": 0}],
            ]
        },
        "Attach Tx (A)":            {"main": [[{"node": "Capture Tx (A)",      "type": "main", "index": 0}]]},
        "Capture Tx (A)":           {"main": [[{"node": "Summarize A (tx)",    "type": "main", "index": 0}]]},

        # PATH B connections
        "Extract Body":             {"main": [[{"node": "Prep Body Asset",     "type": "main", "index": 0}]]},
        "Prep Body Asset":          {"main": [[{"node": "Write Body HTML",     "type": "main", "index": 0}]]},
        "Write Body HTML":          {"main": [[{"node": "Probe Body",          "type": "main", "index": 0}]]},
        "Probe Body":               {"main": [[{"node": "Parse Body Probe",    "type": "main", "index": 0}]]},
        "Parse Body Probe":         {"main": [[{"node": "Body Dedup Query",    "type": "main", "index": 0}]]},
        "Body Dedup Query":         {"main": [[{"node": "Body Dedup Branch",   "type": "main", "index": 0}]]},
        "Body Dedup Branch":        {"main": [[{"node": "Body Dedup?",         "type": "main", "index": 0}]]},
        "Body Dedup?": {
            "main": [
                [{"node": "Summarize B (dedup)",  "type": "main", "index": 0}],
                [{"node": "Insert Body Asset",    "type": "main", "index": 0}],
            ]
        },
        "Insert Body Asset":        {"main": [[{"node": "Body Post Insert",    "type": "main", "index": 0}]]},
        "Body Post Insert":         {"main": [[{"node": "Build Body Prompt",   "type": "main", "index": 0}]]},
        "Build Body Prompt":        {"main": [[{"node": "Haiku Extract Body",  "type": "main", "index": 0}]]},
        "Haiku Extract Body":       {"main": [[{"node": "Parse Body Haiku",    "type": "main", "index": 0}]]},
        "Parse Body Haiku":         {"main": [[{"node": "Update Body Asset",   "type": "main", "index": 0}]]},
        "Update Body Asset":        {"main": [[{"node": "Body Decide Tx",      "type": "main", "index": 0}]]},
        "Body Decide Tx":           {"main": [[{"node": "Body Skip Tx?",       "type": "main", "index": 0}]]},
        "Body Skip Tx?": {
            "main": [
                [{"node": "Summarize B (no tx)", "type": "main", "index": 0}],
                [{"node": "Body Tx",             "type": "main", "index": 0}],
            ]
        },
        "Body Tx":                  {"main": [[{"node": "Body Capture Tx",     "type": "main", "index": 0}]]},
        "Body Capture Tx":          {"main": [[{"node": "Summarize B (tx)",    "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}


# ============================================================
# Save JSON and deploy via API
# ============================================================

with open('/home/michael/KiroProject/n8n-workflows/email-receipts-importer.json', 'w') as f:
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
existing = find_by_name("Email Receipts Importer")
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
# Don't auto-activate — same as before, manual activation after Gmail label setup.
print("(left INACTIVE — activate manually after creating Gmail 'Receipts' label)")
print()
print("v2 enhancements:")
print("  - PATH A (attachments): unchanged from v1")
print("  - PATH B (body receipt): extracts email body text, sends to Haiku,")
print("    creates asset + transaction if receipt data found")
print("  - Both paths run in parallel for every email")
print("  - Dedup on both paths (sha256 for body, Process Asset sha256 for attachments)")
