"""Rebuild the Override Transaction Category workflow with learning loop + retroactive cascade."""
import json
import subprocess
import sys

from _config import API_KEY, N8N_URL
# (use the real one we have; prior line was a typo)
from _config import API_KEY, N8N_URL

WORKFLOW_ID = "NFx7hPsoCzcZ1Sd3"
POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"

# ---- JS code blocks --------------------------------------------------------

validate_code = r"""const body = $input.first().json.body || $input.first().json;
const transaction_id_raw = body.transaction_id;
const category_name_raw = body.category_name || body.new_category;
const transaction_id = (typeof transaction_id_raw === 'string') ? transaction_id_raw.trim() : '';
const category_name = (typeof category_name_raw === 'string') ? category_name_raw.trim() : '';
const create_if_missing = body.create_if_missing === true || body.create_if_missing === 'true';
const apply_to_similar = body.apply_to_similar === true || body.apply_to_similar === 'true';
const confirm_retroactive = body.confirm_retroactive === true || body.confirm_retroactive === 'true';

if (transaction_id.length === 0) {
  return [{ json: { error: 'Missing required parameter: transaction_id', valid: false } }];
}
if (category_name.length === 0) {
  return [{ json: { error: 'Missing required parameter: category_name', valid: false } }];
}

return [{ json: {
  transaction_id,
  transaction_id_sql: transaction_id.replace(/'/g, "''"),
  category_name,
  category_name_sql: category_name.replace(/'/g, "''"),
  create_if_missing,
  apply_to_similar,
  confirm_retroactive,
  valid: true
} }];"""

decide_code = r"""const validated = $('Validate').first().json;
const rows = $input.all();
const categoryId = (rows.length > 0 && rows[0].json) ? rows[0].json.id : null;

if (categoryId !== null && categoryId !== undefined) {
  return [{ json: Object.assign({}, validated, { category_id: categoryId, action: 'update' }) }];
}

if (validated.create_if_missing) {
  return [{ json: Object.assign({}, validated, { action: 'create_then_update' }) }];
}

return [{ json: Object.assign({}, validated, { action: 'error_not_found' }) }];"""

extract_pattern_code = r"""// After we've resolved the target category_id, look up the source transaction's
// description so we can extract a meaningful pattern to learn from.
const validated = $('Validate').first().json;
const decide = $('Decide').first().json;
const rows = $input.all();
const txn = rows.length > 0 ? rows[0].json : null;

if (!txn) {
  return [{ json: { error: 'source_transaction_not_found', message: 'Transaction ' + validated.transaction_id + ' does not exist.' } }];
}

// Extract a "pattern" from the description: take the first alphabetic word
// that's at least 3 chars long. Gives us strong merchant signals like WALMART, AMAZON, ROCKLER.
const raw = (txn.description || '').trim();
const words = raw.split(/[\s*#\-_\.\/,]+/).filter(w => /^[A-Za-z]{3,}$/.test(w));
const pattern = words.length > 0 ? words[0].toUpperCase() : raw.slice(0, 40);

return [{ json: {
  transaction_id: validated.transaction_id,
  transaction_id_sql: validated.transaction_id_sql,
  category_name: validated.category_name,
  category_name_sql: validated.category_name_sql,
  category_id: decide.category_id,
  description: raw,
  pattern,
  pattern_sql: pattern.replace(/'/g, "''"),
  apply_to_similar: validated.apply_to_similar,
  confirm_retroactive: validated.confirm_retroactive
} }];"""

count_similar_code = r"""const ctx = $('Extract Pattern').first().json;
const rows = $input.all();
const similarCount = (rows.length > 0 && rows[0].json) ? parseInt(rows[0].json.cnt, 10) || 0 : 0;

// If user hasn't explicitly opted in to retroactive OR hasn't confirmed yet,
// and there ARE similar transactions, we return a WARN instead of applying.
const shouldWarn = similarCount > 0 && !ctx.confirm_retroactive;

return [{ json: Object.assign({}, ctx, {
  similar_count: similarCount,
  should_warn: shouldWarn
}) }];"""

format_warn_code = r"""const ctx = $input.first().json;
return [{ json: {
  success: false,
  needs_confirmation: true,
  message: 'Re-categorizing this transaction as "' + ctx.category_name + '" will also affect ' + ctx.similar_count + ' other similar transactions (matching pattern "' + ctx.pattern + '"). Confirm with the user. To proceed, call again with confirm_retroactive=true. To only update this single transaction, call again with apply_to_similar=false.',
  pattern: ctx.pattern,
  similar_count: ctx.similar_count,
  new_category: ctx.category_name,
  transaction_id: ctx.transaction_id
} }];"""

format_success_code = r"""const ctx = $('Extract Pattern').first().json;
const primary = $('Update Primary Transaction').all();
const similarUpdate = $('Update Similar Transactions').all();

const primaryRow = primary.length > 0 ? primary[0].json : {};
const similarCount = similarUpdate.length;

const posted = primaryRow.posted_date;
const dateStr = (posted && typeof posted === 'string' && posted.includes('T'))
  ? posted.split('T')[0]
  : posted;

const parts = ['Transaction re-categorized to ' + ctx.category_name + '.'];
if (similarCount > 0) {
  parts.push(similarCount + ' similar transactions (pattern "' + ctx.pattern + '") were also updated.');
}
parts.push('Saved as a learning example for future auto-categorization.');

return [{ json: {
  success: true,
  message: parts.join(' '),
  pattern_learned: ctx.pattern,
  new_category: ctx.category_name,
  retroactive_updates: similarCount,
  transaction: {
    id: primaryRow.id,
    amount: primaryRow.amount != null ? parseFloat(primaryRow.amount) : null,
    description: primaryRow.description,
    posted_date: dateStr,
    user_category_override: primaryRow.user_category_override
  }
} }];"""

format_not_found_code = r"""const validated = $('Validate').first().json;
const rows = $input.all();
const existing = rows.map(r => r.json).filter(r => r.name);

// Group by parent for nicer presentation
const byParent = {};
for (const r of existing) {
  const key = r.parent_name || '(top-level)';
  if (!byParent[key]) byParent[key] = [];
  byParent[key].push(r.name);
}

return [{ json: {
  success: false,
  error: 'category_not_found',
  message: 'Category "' + validated.category_name + '" does not exist. Confirm with the user whether to create it, then call again with create_if_missing=true.',
  existing_categories_by_parent: byParent
} }];"""

error_invalid_code = r"""const v = $('Validate').first().json;
return [{ json: { success: false, error: 'invalid_input', message: v.error } }];"""

# ---- Build workflow --------------------------------------------------------

pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}

# Shared SQL fragments
count_similar_sql = """SELECT COUNT(*) AS cnt
FROM transactions
WHERE UPPER(description) LIKE '%' || UPPER('{{ $json.pattern_sql }}') || '%'
  AND id <> '{{ $json.transaction_id_sql }}'
  AND user_category_override = false;"""

update_similar_sql = """UPDATE transactions
SET category_id = {{ $('Extract Pattern').first().json.category_id }}
WHERE UPPER(description) LIKE '%' || UPPER('{{ $('Extract Pattern').first().json.pattern_sql }}') || '%'
  AND id <> '{{ $('Extract Pattern').first().json.transaction_id_sql }}'
  AND user_category_override = false
RETURNING id;"""

upsert_example_sql = """INSERT INTO category_examples (description_pattern, category_id, source_transaction_id)
VALUES ('{{ $('Extract Pattern').first().json.pattern_sql }}', {{ $('Extract Pattern').first().json.category_id }}, '{{ $('Extract Pattern').first().json.transaction_id_sql }}')
ON CONFLICT (LOWER(description_pattern), category_id)
DO UPDATE SET times_reinforced = category_examples.times_reinforced + 1, updated_at = NOW()
RETURNING id;"""

update_primary_sql = """UPDATE transactions
SET category_id = {{ $('Extract Pattern').first().json.category_id }},
    user_category_override = true
WHERE id = '{{ $('Extract Pattern').first().json.transaction_id_sql }}'
RETURNING id, category_id, amount, description, posted_date, user_category_override;"""

fetch_description_sql = """SELECT id, description FROM transactions WHERE id = '{{ $('Validate').first().json.transaction_id_sql }}';"""

list_categories_sql = """SELECT c.name, p.name AS parent_name
FROM categories c LEFT JOIN categories p ON c.parent_id = p.id
WHERE c.id NOT IN (SELECT DISTINCT parent_id FROM categories WHERE parent_id IS NOT NULL)
ORDER BY p.name NULLS LAST, c.name;"""

check_category_sql = "SELECT (SELECT id FROM categories WHERE LOWER(name) = LOWER('{{ $('Validate').first().json.category_name_sql }}') LIMIT 1) AS id;"

create_category_sql = "INSERT INTO categories (name, is_system) VALUES ('{{ $('Validate').first().json.category_name_sql }}', false) RETURNING id;"

workflow = {
    "name": "Override Transaction Category",
    "description": "Updates a transaction's category, saves the pattern as a learning example, and retroactively applies to similar transactions (with confirmation).",
    "nodes": [
        # Entry
        {
            "parameters": {"path": "update-category", "httpMethod": "POST", "responseMode": "lastNode", "options": {}},
            "id": "webhook-oc", "name": "Webhook",
            "type": "n8n-nodes-base.webhook", "typeVersion": 2.1,
            "position": [200, 500], "webhookId": "update-category-webhook"
        },
        {
            "parameters": {"jsCode": validate_code},
            "id": "validate-oc", "name": "Validate",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [400, 500]
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "cv-oc", "leftValue": "={{ $json.valid }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-valid-oc", "name": "IF Valid",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [600, 500]
        },
        {
            "parameters": {"jsCode": error_invalid_code},
            "id": "input-error-oc", "name": "Return Input Error",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [800, 700]
        },
        # Check category
        {
            "parameters": {"operation": "executeQuery", "query": check_category_sql, "options": {}},
            "id": "check-cat-oc", "name": "Check Category",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [800, 400], "credentials": pg
        },
        {
            "parameters": {"jsCode": decide_code},
            "id": "decide-oc", "name": "Decide",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1000, 400]
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "c-notfound", "leftValue": "={{ $json.action }}", "rightValue": "error_not_found", "operator": {"type": "string", "operation": "equals"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-notfound-oc", "name": "IF Category Not Found",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [1200, 400]
        },
        # Not-found branch
        {
            "parameters": {"operation": "executeQuery", "query": list_categories_sql, "options": {}},
            "id": "list-cats-oc", "name": "List Categories",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [1400, 550], "credentials": pg
        },
        {
            "parameters": {"jsCode": format_not_found_code},
            "id": "format-nf-oc", "name": "Format Not Found",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1600, 550]
        },
        # Exists-or-create branch
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "c-create", "leftValue": "={{ $json.action }}", "rightValue": "create_then_update", "operator": {"type": "string", "operation": "equals"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-create-oc", "name": "IF Create Then Update",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [1400, 300]
        },
        {
            "parameters": {"operation": "executeQuery", "query": create_category_sql, "options": {}},
            "id": "create-cat-oc", "name": "Create Category",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [1600, 200], "credentials": pg
        },
        # Passthrough after create - merge id into Decide context via a Code node
        {
            "parameters": {"jsCode": r"""const decide = $('Decide').first().json;
const rows = $input.all();
const newId = rows[0].json.id;
return [{ json: Object.assign({}, decide, { category_id: newId }) }];"""},
            "id": "merge-create-oc", "name": "Merge Create",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1800, 200]
        },
        # Look up transaction description for pattern extraction
        {
            "parameters": {"operation": "executeQuery", "query": fetch_description_sql, "options": {}},
            "id": "fetch-desc-oc", "name": "Fetch Description",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [2000, 300], "credentials": pg
        },
        {
            "parameters": {"jsCode": extract_pattern_code},
            "id": "extract-pattern-oc", "name": "Extract Pattern",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [2200, 300]
        },
        # Count similar transactions
        {
            "parameters": {"operation": "executeQuery", "query": count_similar_sql, "options": {}},
            "id": "count-similar-oc", "name": "Count Similar",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [2400, 300], "credentials": pg
        },
        {
            "parameters": {"jsCode": count_similar_code},
            "id": "similar-ctx-oc", "name": "Similar Context",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [2600, 300]
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "c-warn", "leftValue": "={{ $json.should_warn }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-warn-oc", "name": "IF Needs Warning",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [2800, 300]
        },
        {
            "parameters": {"jsCode": format_warn_code},
            "id": "format-warn-oc", "name": "Format Warning",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [3000, 450]
        },
        # Apply: update primary, optionally update similar, save example
        {
            "parameters": {"operation": "executeQuery", "query": update_primary_sql, "options": {}},
            "id": "update-primary-oc", "name": "Update Primary Transaction",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [3000, 150], "credentials": pg
        },
        {
            "parameters": {"operation": "executeQuery", "query": update_similar_sql, "options": {}},
            "id": "update-similar-oc", "name": "Update Similar Transactions",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [3200, 150], "credentials": pg
        },
        {
            "parameters": {
                "jsCode": r"""// Collapse multiple Update Similar rows down to a single pass-through item
// so the Save Example node (upsert) only runs once.
return [{ json: $('Extract Pattern').first().json }];"""
            },
            "id": "collapse-oc", "name": "Collapse To One",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [3300, 150]
        },
        {
            "parameters": {"operation": "executeQuery", "query": upsert_example_sql, "options": {}},
            "id": "save-example-oc", "name": "Save Example",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [3400, 150], "credentials": pg
        },
        {
            "parameters": {"jsCode": format_success_code},
            "id": "format-success-oc", "name": "Format Success",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [3600, 150]
        }
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "Validate", "type": "main", "index": 0}]]},
        "Validate": {"main": [[{"node": "IF Valid", "type": "main", "index": 0}]]},
        "IF Valid": {"main": [
            [{"node": "Check Category", "type": "main", "index": 0}],
            [{"node": "Return Input Error", "type": "main", "index": 0}]
        ]},
        "Check Category": {"main": [[{"node": "Decide", "type": "main", "index": 0}]]},
        "Decide": {"main": [[{"node": "IF Category Not Found", "type": "main", "index": 0}]]},
        "IF Category Not Found": {"main": [
            [{"node": "List Categories", "type": "main", "index": 0}],
            [{"node": "IF Create Then Update", "type": "main", "index": 0}]
        ]},
        "List Categories": {"main": [[{"node": "Format Not Found", "type": "main", "index": 0}]]},
        "IF Create Then Update": {"main": [
            [{"node": "Create Category", "type": "main", "index": 0}],
            [{"node": "Fetch Description", "type": "main", "index": 0}]
        ]},
        "Create Category": {"main": [[{"node": "Merge Create", "type": "main", "index": 0}]]},
        "Merge Create": {"main": [[{"node": "Fetch Description", "type": "main", "index": 0}]]},
        "Fetch Description": {"main": [[{"node": "Extract Pattern", "type": "main", "index": 0}]]},
        "Extract Pattern": {"main": [[{"node": "Count Similar", "type": "main", "index": 0}]]},
        "Count Similar": {"main": [[{"node": "Similar Context", "type": "main", "index": 0}]]},
        "Similar Context": {"main": [[{"node": "IF Needs Warning", "type": "main", "index": 0}]]},
        "IF Needs Warning": {"main": [
            [{"node": "Format Warning", "type": "main", "index": 0}],
            [{"node": "Update Primary Transaction", "type": "main", "index": 0}]
        ]},
        "Update Primary Transaction": {"main": [[{"node": "Update Similar Transactions", "type": "main", "index": 0}]]},
        "Update Similar Transactions": {"main": [[{"node": "Collapse To One", "type": "main", "index": 0}]]},
        "Collapse To One": {"main": [[{"node": "Save Example", "type": "main", "index": 0}]]},
        "Save Example": {"main": [[{"node": "Format Success", "type": "main", "index": 0}]]}
    },
    "settings": {"executionOrder": "v1"}
}

with open('/home/michael/KiroProject/n8n-workflows/override-category.json', 'w') as f:
    json.dump(workflow, f, indent=2)
print("Saved override-category.json")

def api(method, path, data=None):
    cmd = ['curl', '-s', '-X', method, '-H', f'X-N8N-API-KEY: {API_KEY}', '-H', 'Content-Type: application/json']
    if data is not None:
        cmd.extend(['-d', json.dumps(data)])
    cmd.append(f'{N8N_URL}/api/v1{path}')
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout) if r.stdout else {}

payload = {k: workflow[k] for k in ['name', 'nodes', 'connections', 'settings']}
payload['description'] = workflow.get('description', '')
resp = api('PUT', f'/workflows/{WORKFLOW_ID}', payload)
print(f"Updated: {resp.get('name')} active={resp.get('active')}")
if 'message' in resp:
    print(f"Error: {resp['message'][:400]}")
