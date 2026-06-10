"""Build and deploy the Override Transaction Category workflow."""
import json
import subprocess
import sys

from _config import API_KEY, N8N_URL
POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"  # Finance Postgres (read/write)

validate_code = r"""const body = $input.first().json.body || $input.first().json;
const transaction_id_raw = body.transaction_id;
const category_name_raw = body.category_name || body.new_category;
const transaction_id = (typeof transaction_id_raw === 'string') ? transaction_id_raw.trim() : '';
const category_name = (typeof category_name_raw === 'string') ? category_name_raw.trim() : '';
const create_if_missing = body.create_if_missing === true || body.create_if_missing === 'true';

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
  valid: true
} }];"""

decide_code = r"""const validated = $('Validate').first().json;
const rows = $input.all();
const categoryId = (rows.length > 0 && rows[0].json) ? rows[0].json.id : null;

if (categoryId !== null && categoryId !== undefined) {
  return [{ json: {
    transaction_id: validated.transaction_id,
    transaction_id_sql: validated.transaction_id_sql,
    category_name: validated.category_name,
    category_name_sql: validated.category_name_sql,
    category_id: categoryId,
    create_if_missing: validated.create_if_missing,
    action: 'update'
  } }];
}

if (validated.create_if_missing) {
  return [{ json: {
    transaction_id: validated.transaction_id,
    transaction_id_sql: validated.transaction_id_sql,
    category_name: validated.category_name,
    category_name_sql: validated.category_name_sql,
    create_if_missing: true,
    action: 'create_then_update'
  } }];
}

return [{ json: {
  transaction_id: validated.transaction_id,
  category_name: validated.category_name,
  action: 'error_not_found'
} }];"""

format_success_code = r"""const rows = $input.all();
const validated = $('Validate').first().json;

if (rows.length === 0 || !rows[0].json || !rows[0].json.id) {
  return [{ json: {
    success: false,
    error: 'transaction_not_found',
    message: 'Transaction ' + validated.transaction_id + ' was not found or could not be updated.'
  } }];
}

const updated = rows[0].json;
const postedDate = updated.posted_date;
const dateStr = (postedDate && typeof postedDate === 'string' && postedDate.includes('T'))
  ? postedDate.split('T')[0]
  : postedDate;

return [{ json: {
  success: true,
  message: 'Transaction re-categorized to ' + validated.category_name + '. Future runs of the Categorizer will skip this transaction.',
  transaction: {
    id: updated.id,
    amount: updated.amount != null ? parseFloat(updated.amount) : null,
    description: updated.description,
    posted_date: dateStr,
    new_category: validated.category_name,
    user_category_override: updated.user_category_override
  }
} }];"""

format_not_found_code = r"""const validated = $('Validate').first().json;
const rows = $input.all();
const existing = rows.map(r => r.json.name).filter(n => n != null).sort();

return [{ json: {
  success: false,
  error: 'category_not_found',
  message: 'Category "' + validated.category_name + '" does not exist. Confirm with the user whether they want to create it, then call this skill again with create_if_missing=true.',
  existing_categories: existing
} }];"""

error_invalid_code = r"""const v = $('Validate').first().json;
return [{ json: { success: false, error: 'invalid_input', message: v.error } }];"""

pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}

workflow = {
    "name": "Override Transaction Category",
    "description": "Updates a transaction's category with user_category_override=true. If category doesn't exist, returns list of valid categories unless create_if_missing=true.",
    "nodes": [
        {
            "parameters": {"path": "update-category", "httpMethod": "POST", "responseMode": "lastNode", "options": {}},
            "id": "webhook-oc", "name": "Webhook", "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1, "position": [200, 400], "webhookId": "update-category-webhook"
        },
        {
            "parameters": {"jsCode": validate_code},
            "id": "validate-oc", "name": "Validate", "type": "n8n-nodes-base.code",
            "typeVersion": 2, "position": [420, 400]
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "cond-valid-oc", "leftValue": "={{ $json.valid }}", "rightValue": True, "operator": {"type": "boolean", "operation": "true"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-valid-oc", "name": "IF Valid", "type": "n8n-nodes-base.if",
            "typeVersion": 2, "position": [640, 400]
        },
        {
            "parameters": {"jsCode": error_invalid_code},
            "id": "input-error-oc", "name": "Return Input Error",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [860, 600]
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "SELECT (SELECT id FROM categories WHERE LOWER(name) = LOWER('{{ $('Validate').first().json.category_name_sql }}') LIMIT 1) AS id;",
                "options": {}
            },
            "id": "check-cat-oc", "name": "Check Category",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [860, 300], "credentials": pg
        },
        {
            "parameters": {"jsCode": decide_code},
            "id": "decide-oc", "name": "Decide",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1080, 300]
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "cond-err-oc", "leftValue": "={{ $json.action }}", "rightValue": "error_not_found", "operator": {"type": "string", "operation": "equals"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-err-oc", "name": "IF Error Not Found",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [1300, 300]
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "SELECT name FROM categories ORDER BY name;",
                "options": {}
            },
            "id": "list-cats-oc", "name": "List Categories",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [1520, 500], "credentials": pg
        },
        {
            "parameters": {"jsCode": format_not_found_code},
            "id": "format-nf-oc", "name": "Format Not Found",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1740, 500]
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "cond-create-oc", "leftValue": "={{ $json.action }}", "rightValue": "create_then_update", "operator": {"type": "string", "operation": "equals"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-create-oc", "name": "IF Create Then Update",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [1520, 200]
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "INSERT INTO categories (name, is_system) VALUES ('{{ $('Validate').first().json.category_name_sql }}', false) RETURNING id;",
                "options": {}
            },
            "id": "create-cat-oc", "name": "Create Category",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [1740, 100], "credentials": pg
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "UPDATE transactions SET category_id = {{ $json.id }}, user_category_override = true WHERE id = '{{ $('Validate').first().json.transaction_id_sql }}' RETURNING id, category_id, amount, description, posted_date, user_category_override;",
                "options": {}
            },
            "id": "update-txn-a-oc", "name": "Update Transaction (after create)",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [1960, 100], "credentials": pg
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "UPDATE transactions SET category_id = {{ $('Decide').first().json.category_id }}, user_category_override = true WHERE id = '{{ $('Validate').first().json.transaction_id_sql }}' RETURNING id, category_id, amount, description, posted_date, user_category_override;",
                "options": {}
            },
            "id": "update-txn-b-oc", "name": "Update Transaction (direct)",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [1740, 300], "credentials": pg
        },
        {
            "parameters": {"jsCode": format_success_code},
            "id": "format-success-oc", "name": "Format Success",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [2180, 200]
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
        "Decide": {"main": [[{"node": "IF Error Not Found", "type": "main", "index": 0}]]},
        "IF Error Not Found": {"main": [
            [{"node": "List Categories", "type": "main", "index": 0}],
            [{"node": "IF Create Then Update", "type": "main", "index": 0}]
        ]},
        "List Categories": {"main": [[{"node": "Format Not Found", "type": "main", "index": 0}]]},
        "IF Create Then Update": {"main": [
            [{"node": "Create Category", "type": "main", "index": 0}],
            [{"node": "Update Transaction (direct)", "type": "main", "index": 0}]
        ]},
        "Create Category": {"main": [[{"node": "Update Transaction (after create)", "type": "main", "index": 0}]]},
        "Update Transaction (after create)": {"main": [[{"node": "Format Success", "type": "main", "index": 0}]]},
        "Update Transaction (direct)": {"main": [[{"node": "Format Success", "type": "main", "index": 0}]]}
    },
    "settings": {"executionOrder": "v1"}
}

# Save to the workflows folder
with open('/home/michael/KiroProject/n8n-workflows/override-category.json', 'w') as f:
    json.dump(workflow, f, indent=2)
print("Saved to override-category.json")

# Deploy to n8n
def api(method, path, data=None):
    cmd = ['curl', '-s', '-X', method,
           '-H', f'X-N8N-API-KEY: {API_KEY}',
           '-H', 'Content-Type: application/json']
    if data is not None:
        cmd.extend(['-d', json.dumps(data)])
    cmd.append(f'{N8N_URL}/api/v1{path}')
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout else {}

# Create the workflow
# Strip fields n8n API doesn't accept (only name, nodes, connections, settings allowed on create)
deploy_payload = {k: workflow[k] for k in ['name', 'nodes', 'connections', 'settings']}
resp = api('POST', '/workflows', deploy_payload)
if 'id' not in resp:
    print(f"Deploy failed: {resp}")
    sys.exit(1)

wf_id = resp['id']
print(f"Created workflow: {wf_id}")

# Activate it
act = api('POST', f'/workflows/{wf_id}/activate')
print(f"Activated: {act.get('active')}")
print(f"Workflow ID: {wf_id}")
