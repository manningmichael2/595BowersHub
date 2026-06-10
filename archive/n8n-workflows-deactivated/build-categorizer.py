"""Rebuild the Categorizer workflow with the new hierarchy and learning loop."""
import json
import subprocess
import sys

from _config import API_KEY, N8N_URL
WORKFLOW_ID = "onU76wM0FSSeMJ9h"  # existing Categorizer
POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"
ANTHROPIC_CRED_ID = "uGfcnvWQfj3IfjsH"

build_prompt_code = r"""const categories = $('Fetch Categories').all().map(i => i.json);
const examples = $('Fetch Examples').all().map(i => i.json);
const transactions = $('Fetch Uncategorized').all().map(i => i.json);

if (transactions.length === 0) {
  return [{ json: { skip: true, count: 0, reason: 'No uncategorized transactions' } }];
}

// A "leaf" is any category that has no children.
// This includes both top-level categories (like 'Other', 'Subscriptions') AND
// sub-categories under a parent (like 'Food_Groceries' under 'Food').
const childIds = new Set(categories.map(c => c.parent_id).filter(p => p !== null));
const leaves = categories.filter(c => !childIds.has(c.id));

// Build the category tree for the prompt (shows parent/leaf for context)
const tree = [];
for (const leaf of leaves) {
  const parent = leaf.parent_id ? categories.find(c => c.id === leaf.parent_id) : null;
  tree.push(parent ? (parent.name + '/' + leaf.name) : leaf.name);
}
tree.sort();

// Category name -> id lookup (leaves only - these are the valid choices)
const categoryIdByName = {};
for (const leaf of leaves) {
  categoryIdByName[leaf.name] = leaf.id;
}

// Build few-shot examples section
const exampleLines = examples
  .filter(e => e.description_pattern && e.category_name)
  .slice(0, 30)
  .map(e => '"' + e.description_pattern + '" -> ' + e.category_name);

const examplesBlock = exampleLines.length > 0
  ? '\n\nHere are past categorization decisions made by the user. Use these as strong guidance:\n' + exampleLines.join('\n')
  : '';

// Batch transactions into groups of 50
const batches = [];
for (let i = 0; i < transactions.length; i += 50) {
  batches.push(transactions.slice(i, i + 50));
}

const output = [];
for (let idx = 0; idx < batches.length; idx++) {
  const batch = batches[idx];
  const txnData = batch.map(t => ({
    id: t.id,
    description: t.description || '',
    memo: t.memo || '',
    amount: parseFloat(t.amount)
  }));

  const prompt = 'Categorize each bank transaction below. Choose the MOST specific leaf category from this list (only use the leaf name, not the parent):\n\n' +
    tree.join('\n') +
    '\n\nRules:\n' +
    '- Transfers between your own accounts -> Transfer\n' +
    '- Paychecks, interest, dividends -> Income\n' +
    '- Woodworking tools/supplies (Rockler, Festool, Harbor Freight, blades, wood) -> Woodshop\n' +
    '- Airlines, hotels, travel insurance, AMEX travel -> Travel\n' +
    '- Grocery stores, food markets (Kroger, Meijer, Costco food) -> Food_Groceries\n' +
    '- Restaurants, food delivery, Uber Eats -> Food_Dining\n' +
    '- Gas stations, vehicle fuel -> Trans_Gas\n' +
    '- Streaming, software, memberships -> Subscriptions\n' +
    '- When unsure -> Other\n' +
    examplesBlock +
    '\n\nReturn ONLY a JSON array, no markdown, no explanation: [{"id":"<id>","category":"<leaf_name>"}, ...]\n\nTransactions:\n' +
    JSON.stringify(txnData);

  output.push({ json: {
    batch_index: idx,
    total_batches: batches.length,
    prompt,
    batch_ids: batch.map(t => t.id),
    category_id_map: categoryIdByName
  } });
}

return output;"""

parse_response_code = r"""// Runs once per Haiku response (one per batch).
// Corresponding Build Prompt output is at the same index.
const txnBatch = $('Build Prompt').all()[$itemIndex];
const categoryIdMap = txnBatch.json.category_id_map;
const content = ($json.content && $json.content[0]) ? $json.content[0].text : '';

let parsed;
try {
  let clean = content.trim();
  if (clean.startsWith('```')) {
    clean = clean.replace(/^```(?:json)?\n?/, '').replace(/\n?```$/, '').trim();
  }
  const match = clean.match(/\[[\s\S]*\]/);
  if (!match) throw new Error('No JSON array found');
  parsed = JSON.parse(match[0]);
} catch (err) {
  // Fallback: assign all ids in this batch to Other
  const otherId = categoryIdMap['Other'];
  const fallback = txnBatch.json.batch_ids.map(id => ({ id, category_id: otherId, fallback: true }));
  return { json: { items: fallback } };
}

const results = [];
for (const item of parsed) {
  const catName = item.category;
  const catId = categoryIdMap[catName] || categoryIdMap['Other'];
  results.push({
    id: item.id,
    category_id: catId,
    assigned_category: catName,
    fallback: !categoryIdMap[catName]
  });
}

return { json: { items: results } };"""

skip_check_code = r"""// When no uncategorized transactions, short-circuit gracefully
return [{ json: $input.first().json }];"""

pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}
anthropic = {"httpHeaderAuth": {"id": ANTHROPIC_CRED_ID, "name": "Anthropic API"}}

workflow = {
    "name": "Categorizer",
    "description": "Categorizes uncategorized transactions using Haiku, with user examples as few-shot guidance",
    "nodes": [
        {
            "parameters": {"workflowInputs": {"values": [{"name": "trigger", "type": "any"}]}},
            "id": "trigger-cat", "name": "Execute Workflow Trigger",
            "type": "n8n-nodes-base.executeWorkflowTrigger", "typeVersion": 1.1,
            "position": [200, 300]
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "SELECT id, name, parent_id FROM categories ORDER BY COALESCE(parent_id, id), name;",
                "options": {}
            },
            "id": "fetch-cats", "name": "Fetch Categories",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [400, 200], "credentials": pg
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "SELECT e.description_pattern, c.name AS category_name, e.times_reinforced FROM category_examples e JOIN categories c ON e.category_id = c.id ORDER BY e.times_reinforced DESC, e.updated_at DESC LIMIT 30;",
                "options": {}
            },
            "id": "fetch-examples", "name": "Fetch Examples",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [400, 350], "credentials": pg
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "SELECT id, description, memo, amount FROM transactions WHERE category_id IS NULL AND user_category_override = false ORDER BY posted_date DESC LIMIT 500;",
                "options": {}
            },
            "id": "fetch-uncat", "name": "Fetch Uncategorized",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [400, 500], "credentials": pg
        },
        {
            "parameters": {"jsCode": build_prompt_code},
            "id": "build-prompt", "name": "Build Prompt",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [640, 350]
        },
        {
            "parameters": {
                "conditions": {
                    "options": {"caseSensitive": True},
                    "conditions": [{"id": "cond-has-work", "leftValue": "={{ $json.skip }}", "rightValue": True, "operator": {"type": "boolean", "operation": "notEquals"}}],
                    "combinator": "and"
                },
                "options": {}
            },
            "id": "if-has-work", "name": "IF Has Work",
            "type": "n8n-nodes-base.if", "typeVersion": 2, "position": [860, 350]
        },
        {
            "parameters": {
                "method": "POST",
                "url": "https://api.anthropic.com/v1/messages",
                "authentication": "genericCredentialType",
                "genericAuthType": "httpHeaderAuth",
                "sendHeaders": True,
                "headerParameters": {
                    "parameters": [
                        {"name": "anthropic-version", "value": "2023-06-01"},
                        {"name": "content-type", "value": "application/json"}
                    ]
                },
                "sendBody": True,
                "specifyBody": "json",
                "jsonBody": "={{ JSON.stringify({ model: 'claude-haiku-4-5-20251001', max_tokens: 4096, messages: [{ role: 'user', content: $json.prompt }] }) }}",
                "options": {"timeout": 60000}
            },
            "id": "call-haiku", "name": "Call Haiku",
            "type": "n8n-nodes-base.httpRequest", "typeVersion": 4.2,
            "position": [1080, 250], "credentials": anthropic
        },
        {
            "parameters": {
                "mode": "runOnceForEachItem",
                "jsCode": parse_response_code
            },
            "id": "parse-response", "name": "Parse Response",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1300, 250]
        },
        {
            "parameters": {
                "fieldToSplitOut": "items",
                "options": {}
            },
            "id": "split-items", "name": "Split Out Items",
            "type": "n8n-nodes-base.splitOut", "typeVersion": 1,
            "position": [1500, 250]
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "UPDATE transactions SET category_id = {{ $json.category_id }} WHERE id = '{{ $json.id }}' AND user_category_override = false AND category_id IS NULL;",
                "options": {}
            },
            "id": "update-cats", "name": "Update Categories",
            "type": "n8n-nodes-base.postgres", "typeVersion": 2.5,
            "position": [1720, 250], "credentials": pg
        },
        {
            "parameters": {"jsCode": skip_check_code},
            "id": "log-skip", "name": "Log Skip",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [1080, 500]
        }
    ],
    "connections": {
        "Execute Workflow Trigger": {"main": [[
            {"node": "Fetch Categories", "type": "main", "index": 0},
            {"node": "Fetch Examples", "type": "main", "index": 0},
            {"node": "Fetch Uncategorized", "type": "main", "index": 0}
        ]]},
        "Fetch Uncategorized": {"main": [[{"node": "Build Prompt", "type": "main", "index": 0}]]},
        "Build Prompt": {"main": [[{"node": "IF Has Work", "type": "main", "index": 0}]]},
        "IF Has Work": {"main": [
            [{"node": "Call Haiku", "type": "main", "index": 0}],
            [{"node": "Log Skip", "type": "main", "index": 0}]
        ]},
        "Call Haiku": {"main": [[{"node": "Parse Response", "type": "main", "index": 0}]]},
        "Parse Response": {"main": [[{"node": "Split Out Items", "type": "main", "index": 0}]]},
        "Split Out Items": {"main": [[{"node": "Update Categories", "type": "main", "index": 0}]]}
    },
    "settings": {"executionOrder": "v1"}
}

# Save to file
with open('/home/michael/KiroProject/n8n-workflows/categorizer.json', 'w') as f:
    json.dump(workflow, f, indent=2)
print("Saved categorizer.json")

# Deploy (update existing workflow)
def api(method, path, data=None):
    cmd = ['curl', '-s', '-X', method,
           '-H', f'X-N8N-API-KEY: {API_KEY}',
           '-H', 'Content-Type: application/json']
    if data is not None:
        cmd.extend(['-d', json.dumps(data)])
    cmd.append(f'{N8N_URL}/api/v1{path}')
    result = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(result.stdout) if result.stdout else {}

# PUT to replace
payload = {k: workflow[k] for k in ['name', 'nodes', 'connections', 'settings']}
payload['description'] = workflow.get('description', '')
resp = api('PUT', f'/workflows/{WORKFLOW_ID}', payload)
print(f"Updated: {resp.get('name')} active={resp.get('active')}")
if 'message' in resp:
    print(f"Error: {resp['message'][:400]}")
