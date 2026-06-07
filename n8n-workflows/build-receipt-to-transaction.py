"""
Build the 'Receipt → Transaction' n8n sub-workflow.

Purpose: take a `files.assets` row (already processed by Process Asset, with
domain='receipt' and ai_extracted populated) and turn it into a
public.transactions row + a public.transaction_files link.

Triggered by:
  - Webhook  POST /webhook/receipt-to-transaction
  - executeWorkflow from any other workflow (email-receipts importer, manual
    upload UI, etc.)

Inputs (JSON body):
  {
    "asset_id":   "uuid",            # required
    "account_id": "ABC123" | null,   # optional, defaults to 'EMAIL_RECEIPT'
    "uploaded_by": "michael"         # optional, for transactions.memo notes
  }

Output:
  {
    "ok": true,
    "transaction_id": "email:<asset_id>",
    "asset_id": "uuid",
    "amount": -17.49,
    "merchant": "HOME DEPOT",
    "posted_date": "2026-05-13",
    "skipped": false           # true if already imported (idempotent)
  }
"""
import json
import subprocess

from _config import API_KEY, N8N_URL
POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"

# ============================================================
# Validate input
# ============================================================
validate_code = r"""const body = $input.first().json.body || $input.first().json;
const assetId = (body.asset_id || "").trim();
if (!assetId) throw new Error("Missing 'asset_id'");

return [{
  json: {
    asset_id:    assetId,
    account_id:  body.account_id || "EMAIL_RECEIPT",
    uploaded_by: body.uploaded_by || "unknown",
    started_at:  Date.now(),
  }
}];
"""

# ============================================================
# Fetch the asset row
# ============================================================
fetch_asset_query = (
    "SELECT id::text AS asset_id, domain, ai_extracted, ai_summary, mime, original_name "
    "FROM files.assets WHERE id = '{{$json.asset_id}}'::uuid LIMIT 1"
)
parse_asset_code = r"""const ctx = $('Validate').first().json;
const rows = $input.all().map(i => i.json).filter(r => r && r.asset_id);
if (rows.length === 0) {
  throw new Error(`asset_id ${ctx.asset_id} not found in files.assets`);
}
const a = rows[0];
if (a.domain !== 'receipt') {
  throw new Error(`asset domain is '${a.domain}', expected 'receipt'`);
}
const x = a.ai_extracted || {};

// Be defensive: vision can return missing/garbage fields.
const merchant = (x.merchant || "Unknown merchant").toString().slice(0, 200);
const total    = (typeof x.total === 'number') ? x.total : null;
const date     = (x.date && /^\d{4}-\d{2}-\d{2}$/.test(x.date)) ? x.date : null;
const payment  = (x.payment_method || "").toString().slice(0, 80);

if (total === null) {
  throw new Error(`Receipt has no parseable total. ai_extracted=${JSON.stringify(x)}`);
}

// Build the transactions row.
// id: deterministic per-asset so re-imports are idempotent.
const txId       = `email:${a.asset_id}`;
const amount     = -Math.abs(total);              // spending = negative
const postedDate = date || (new Date().toISOString().slice(0,10));
const description = merchant;
// memo holds the extra context.
const memoBits = [];
if (payment) memoBits.push(`paid via ${payment}`);
if (a.original_name) memoBits.push(`source: ${a.original_name}`);
if (a.ai_summary) memoBits.push(a.ai_summary);
const memo = memoBits.join(' | ').slice(0, 500);

return [{
  json: {
    ...ctx,
    asset_id:     a.asset_id,
    transaction_id: txId,
    amount:       amount,
    posted_date:  postedDate,
    description:  description,
    memo:         memo,
    merchant:     merchant,
    total:        total,
    payment_method: payment,
    extracted_date: date,
  }
}];
"""

# ============================================================
# Existence pre-check (definitive idempotency signal).
# We run this BEFORE the insert so the response can confidently report
# whether this is a fresh import or a re-run.
# ============================================================
existence_query = (
    "SELECT id::text AS id FROM public.transactions "
    "WHERE id = '{{$json.transaction_id}}' LIMIT 1"
)

existence_branch_code = r"""const ctx = $('Parse Asset').first().json;
const rows = $input.all().map(i => i.json).filter(r => r && r.id);
return [{ json: { ...ctx, already_exists: rows.length > 0 } }];
"""

# ============================================================
# Insert transaction (ON CONFLICT DO NOTHING for idempotency)
# ============================================================
insert_tx_query = (
    "INSERT INTO public.transactions "
    "(id, account_id, posted_date, amount, description, memo, source) "
    "VALUES ("
    "  '{{$json.transaction_id}}', "
    "  '{{$json.account_id}}', "
    "  '{{$json.posted_date}}', "
    "  {{$json.amount}}, "
    "  '{{($json.description || '').replace(/'/g, \"''\")}}', "
    "  '{{($json.memo || '').replace(/'/g, \"''\")}}', "
    "  'email'"
    ") "
    "ON CONFLICT (id) DO NOTHING"
)

# ============================================================
# Pass-through after insert (Postgres node alwaysOutputData kicks in;
# we don't actually care what it returned — `already_exists` from the
# pre-check is the source of truth).
# ============================================================
post_insert_code = r"""const ctx = $('Existence Branch').first().json;
return [{ json: ctx }];
"""

# ============================================================
# Link asset to transaction (idempotent via PK)
# ============================================================
link_query = (
    "INSERT INTO public.transaction_files (transaction_id, asset_id, is_primary) "
    "VALUES ('{{$json.transaction_id}}', '{{$json.asset_id}}'::uuid, true) "
    "ON CONFLICT (transaction_id, asset_id) DO NOTHING"
)

# ============================================================
# Format response
# ============================================================
format_response_code = r"""const ctx = $('Existence Branch').first().json;
return [{
  json: {
    ok: true,
    transaction_id: ctx.transaction_id,
    asset_id:       ctx.asset_id,
    amount:         ctx.amount,
    merchant:       ctx.merchant,
    posted_date:    ctx.posted_date,
    skipped:        !!ctx.already_exists,
    duration_ms:    Date.now() - (ctx.started_at || Date.now()),
  }
}];
"""

# ============================================================
# Build workflow
# ============================================================
pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}

workflow = {
    "name": "Receipt to Transaction",
    "nodes": [
        {
            "parameters": {
                "path": "receipt-to-transaction",
                "httpMethod": "POST",
                "responseMode": "lastNode",
                "options": {},
            },
            "id": "n-webhook",
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [200, 400],
            "webhookId": "receipt-to-transaction-webhook",
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
                "operation": "executeQuery",
                "query": fetch_asset_query,
                "options": {},
            },
            "id": "n-fetch",
            "name": "Fetch Asset",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [600, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": parse_asset_code},
            "id": "n-parse",
            "name": "Parse Asset",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [800, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": existence_query,
                "options": {},
            },
            "id": "n-exist",
            "name": "Existence Check",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [900, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": existence_branch_code},
            "id": "n-exist-branch",
            "name": "Existence Branch",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [950, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": insert_tx_query,
                "options": {},
            },
            "id": "n-insert-tx",
            "name": "Insert Transaction",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1000, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": post_insert_code},
            "id": "n-post-insert",
            "name": "Post Insert",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1200, 400],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": link_query,
                "options": {},
            },
            "id": "n-link",
            "name": "Link Asset",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [1400, 400],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": format_response_code},
            "id": "n-format",
            "name": "Format Response",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1600, 400],
        },
    ],
    "connections": {
        "Webhook":            {"main": [[{"node": "Validate",            "type": "main", "index": 0}]]},
        "Execute Workflow Trigger": {"main": [[{"node": "Validate",      "type": "main", "index": 0}]]},
        "Validate":           {"main": [[{"node": "Fetch Asset",         "type": "main", "index": 0}]]},
        "Fetch Asset":        {"main": [[{"node": "Parse Asset",         "type": "main", "index": 0}]]},
        "Parse Asset":        {"main": [[{"node": "Existence Check",     "type": "main", "index": 0}]]},
        "Existence Check":    {"main": [[{"node": "Existence Branch",    "type": "main", "index": 0}]]},
        "Existence Branch":   {"main": [[{"node": "Insert Transaction",  "type": "main", "index": 0}]]},
        "Insert Transaction": {"main": [[{"node": "Post Insert",         "type": "main", "index": 0}]]},
        "Post Insert":        {"main": [[{"node": "Link Asset",          "type": "main", "index": 0}]]},
        "Link Asset":         {"main": [[{"node": "Format Response",     "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}


with open('/home/michael/KiroProject/n8n-workflows/receipt-to-transaction.json', 'w') as f:
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
existing = find_by_name("Receipt to Transaction")
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
if wf_id:
    act = api('POST', f'/workflows/{wf_id}/activate')
    print(f"Active: {act.get('active')}")
    print(f"Webhook: {N8N_URL}/webhook/receipt-to-transaction")
