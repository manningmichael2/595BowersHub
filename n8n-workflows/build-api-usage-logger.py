"""
Build the 'API Usage Logger' n8n sub-workflow.

A lightweight workflow that accepts token usage data and INSERTs it into
public.api_usage_log. Called via Execute Workflow from any workflow that
makes Anthropic API calls.

Also exposes a webhook GET /webhook/api-usage for the dashboard to query
recent usage stats.

Inputs (via Execute Workflow or webhook POST /webhook/log-api-usage):
  {
    "workflow_name": "Smart Capture",
    "node_name": "Classify (Haiku)",
    "model": "claude-haiku-4-5-20251001",
    "input_tokens": 1234,
    "output_tokens": 567,
    "cache_read_tokens": 0,
    "cache_write_tokens": 0,
    "duration_ms": 1500
  }

Query endpoint (GET /webhook/api-usage?days=7):
  Returns daily/workflow/model breakdown of spend.
"""
import json
import subprocess

from _config import API_KEY, N8N_URL

POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"

# Pricing per million tokens (as of May 2026)
# https://docs.anthropic.com/en/docs/about-claude/pricing
PRICING_COMMENT = """
claude-haiku-4-5-20251001:  input $0.80/MTok, output $4.00/MTok
claude-sonnet-4-5-20250514: input $3.00/MTok, output $15.00/MTok
claude-opus-4-20250514:     input $15.00/MTok, output $75.00/MTok
Cache read: 10% of input price. Cache write: 25% of input price.
"""


def api(method, path, data=None):
    cmd = ["curl", "-s", "-X", method,
           "-H", f"X-N8N-API-KEY: {API_KEY}",
           "-H", "Content-Type: application/json"]
    if data is not None:
        cmd.extend(["-d", json.dumps(data)])
    cmd.append(f"{N8N_URL}/api/v1{path}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout) if r.stdout.strip() else {}


# ===================================================================
# LOG BRANCH — receives usage data, calculates cost, inserts into DB
# ===================================================================

# Code node: calculate cost based on model pricing
calc_cost_code = r"""// Calculate estimated cost from token counts and model
const raw = $json;
// Data may come from Execute Workflow (full item with _usage_log) or webhook (direct fields)
const data = raw._usage_log || raw.body || raw;

const model = (data.model || '').toLowerCase();
const inputTok = data.input_tokens || 0;
const outputTok = data.output_tokens || 0;
const cacheRead = data.cache_read_tokens || 0;
const cacheWrite = data.cache_write_tokens || 0;

// Pricing per million tokens (May 2026)
const PRICING = {
  'claude-haiku-4-5-20251001':  { input: 0.80, output: 4.00 },
  'claude-sonnet-4-5-20250514': { input: 3.00, output: 15.00 },
  'claude-sonnet-4-20250514':   { input: 3.00, output: 15.00 },
  'claude-opus-4-20250514':     { input: 15.00, output: 75.00 },
};

// Find matching pricing (partial match for model variants)
let prices = null;
for (const [key, val] of Object.entries(PRICING)) {
  if (model.includes(key) || key.includes(model)) {
    prices = val;
    break;
  }
}

// Fallback: assume Haiku pricing if unknown
if (!prices) {
  // Try to detect from model name
  if (model.includes('haiku')) prices = PRICING['claude-haiku-4-5-20251001'];
  else if (model.includes('opus')) prices = PRICING['claude-opus-4-20250514'];
  else if (model.includes('sonnet')) prices = PRICING['claude-sonnet-4-5-20250514'];
  else prices = { input: 3.00, output: 15.00 }; // default to Sonnet
}

const inputCost = (inputTok / 1_000_000) * prices.input;
const outputCost = (outputTok / 1_000_000) * prices.output;
const cacheReadCost = (cacheRead / 1_000_000) * (prices.input * 0.1);
const cacheWriteCost = (cacheWrite / 1_000_000) * (prices.input * 0.25);
const totalCost = inputCost + outputCost + cacheReadCost + cacheWriteCost;

return [{
  json: {
    workflow_name: data.workflow_name || 'unknown',
    node_name: data.node_name || 'unknown',
    model: data.model || 'unknown',
    input_tokens: inputTok,
    output_tokens: outputTok,
    cache_read_tokens: cacheRead,
    cache_write_tokens: cacheWrite,
    cost_usd: Math.round(totalCost * 1_000_000) / 1_000_000, // 6 decimal places
    duration_ms: data.duration_ms || null,
    metadata: data.metadata || null,
  }
}];
"""

# ===================================================================
# QUERY BRANCH — returns usage stats for the dashboard
# ===================================================================

query_stats_code = r"""// Format the query results for the dashboard
const rows = $input.all().map(i => i.json);

// Group by day
const byDay = {};
const byWorkflow = {};
const byModel = {};
let totalCost = 0;
let totalCalls = 0;

for (const row of rows) {
  const day = row.day || 'unknown';
  const wf = row.workflow_name || 'unknown';
  const mdl = row.model || 'unknown';
  const cost = parseFloat(row.total_cost) || 0;
  const calls = parseInt(row.call_count) || 0;

  if (!byDay[day]) byDay[day] = { cost: 0, calls: 0, input_tokens: 0, output_tokens: 0 };
  byDay[day].cost += cost;
  byDay[day].calls += calls;
  byDay[day].input_tokens += parseInt(row.total_input) || 0;
  byDay[day].output_tokens += parseInt(row.total_output) || 0;

  if (!byWorkflow[wf]) byWorkflow[wf] = { cost: 0, calls: 0 };
  byWorkflow[wf].cost += cost;
  byWorkflow[wf].calls += calls;

  if (!byModel[mdl]) byModel[mdl] = { cost: 0, calls: 0 };
  byModel[mdl].cost += cost;
  byModel[mdl].calls += calls;

  totalCost += cost;
  totalCalls += calls;
}

return [{
  json: {
    ok: true,
    days_queried: Object.keys(byDay).length,
    total_cost_usd: Math.round(totalCost * 100) / 100,
    total_calls: totalCalls,
    by_day: byDay,
    by_workflow: byWorkflow,
    by_model: byModel,
  }
}];
"""


# ===================================================================
# BUILD THE WORKFLOW
# ===================================================================

def build():
    # Check if workflow already exists by name
    existing = api("GET", "/workflows?limit=100")
    wf_id = None
    for wf in existing.get("data", []):
        if wf.get("name") == "API Usage Logger":
            wf_id = wf["id"]
            break

    postgres_creds = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}

    nodes = [
        # --- LOG BRANCH ---
        {
            "id": "trigger-log",
            "name": "Log Trigger",
            "type": "n8n-nodes-base.executeWorkflowTrigger",
            "typeVersion": 1,
            "position": [200, 200],
            "parameters": {},
        },
        {
            "id": "calc-cost",
            "name": "Calculate Cost",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [420, 200],
            "parameters": {
                "jsCode": calc_cost_code,
            },
        },
        {
            "id": "insert-log",
            "name": "Insert Log",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [640, 200],
            "credentials": postgres_creds,
            "parameters": {
                "operation": "executeQuery",
                "query": (
                    "INSERT INTO public.api_usage_log "
                    "(workflow_name, node_name, model, input_tokens, output_tokens, "
                    "cache_read_tokens, cache_write_tokens, cost_usd, duration_ms, metadata) "
                    "VALUES ("
                    "'{{ $json.workflow_name }}', "
                    "'{{ $json.node_name }}', "
                    "'{{ $json.model }}', "
                    "{{ $json.input_tokens }}, "
                    "{{ $json.output_tokens }}, "
                    "{{ $json.cache_read_tokens }}, "
                    "{{ $json.cache_write_tokens }}, "
                    "{{ $json.cost_usd }}, "
                    "{{ $json.duration_ms || 'NULL' }}, "
                    "{{ $json.metadata ? \"'\" + JSON.stringify($json.metadata).replace(/'/g, \"''\") + \"'::jsonb\" : 'NULL' }}"
                    ")"
                ),
                "options": {},
            },
        },
        # --- QUERY BRANCH (webhook) ---
        {
            "id": "webhook-query",
            "name": "Query Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [200, 500],
            "parameters": {
                "path": "api-usage",
                "httpMethod": "GET",
                "responseMode": "lastNode",
                "options": {},
            },
            "webhookId": "api-usage-query",
        },
        {
            "id": "query-stats",
            "name": "Query Stats",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [420, 500],
            "credentials": postgres_creds,
            "parameters": {
                "operation": "executeQuery",
                "query": (
                    "SELECT "
                    "  called_at::date::text AS day, "
                    "  workflow_name, "
                    "  model, "
                    "  COUNT(*)::text AS call_count, "
                    "  SUM(input_tokens)::text AS total_input, "
                    "  SUM(output_tokens)::text AS total_output, "
                    "  SUM(cost_usd)::text AS total_cost "
                    "FROM public.api_usage_log "
                    "WHERE called_at > now() - interval '{{ $json.query.days || 7 }} days' "
                    "GROUP BY day, workflow_name, model "
                    "ORDER BY day DESC, total_cost DESC"
                ),
                "options": {"alwaysOutputData": True},
            },
        },
        {
            "id": "format-stats",
            "name": "Format Stats",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [640, 500],
            "parameters": {
                "jsCode": query_stats_code,
            },
        },
        # --- POST webhook for manual logging (from dashboard or scripts) ---
        {
            "id": "webhook-log",
            "name": "Log Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2,
            "position": [200, 800],
            "parameters": {
                "path": "log-api-usage",
                "httpMethod": "POST",
                "responseMode": "lastNode",
                "options": {},
            },
            "webhookId": "log-api-usage",
        },
        {
            "id": "calc-cost-webhook",
            "name": "Calculate Cost (Webhook)",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [420, 800],
            "parameters": {
                "jsCode": calc_cost_code.replace("$json", "$json.body || $json"),
            },
        },
        {
            "id": "insert-log-webhook",
            "name": "Insert Log (Webhook)",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.5,
            "position": [640, 800],
            "credentials": postgres_creds,
            "parameters": {
                "operation": "executeQuery",
                "query": (
                    "INSERT INTO public.api_usage_log "
                    "(workflow_name, node_name, model, input_tokens, output_tokens, "
                    "cache_read_tokens, cache_write_tokens, cost_usd, duration_ms, metadata) "
                    "VALUES ("
                    "'{{ $json.workflow_name }}', "
                    "'{{ $json.node_name }}', "
                    "'{{ $json.model }}', "
                    "{{ $json.input_tokens }}, "
                    "{{ $json.output_tokens }}, "
                    "{{ $json.cache_read_tokens }}, "
                    "{{ $json.cache_write_tokens }}, "
                    "{{ $json.cost_usd }}, "
                    "{{ $json.duration_ms || 'NULL' }}, "
                    "{{ $json.metadata ? \"'\" + JSON.stringify($json.metadata).replace(/'/g, \"''\") + \"'::jsonb\" : 'NULL' }}"
                    ") RETURNING id::text, cost_usd::text"
                ),
                "options": {},
            },
        },
        {
            "id": "respond-log-webhook",
            "name": "Respond OK",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [860, 800],
            "parameters": {
                "jsCode": "return [{ json: { ok: true, id: $json.id, cost_usd: $json.cost_usd } }];",
            },
        },
    ]

    connections = {
        "Log Trigger": {"main": [[{"node": "Calculate Cost", "type": "main", "index": 0}]]},
        "Calculate Cost": {"main": [[{"node": "Insert Log", "type": "main", "index": 0}]]},
        "Query Webhook": {"main": [[{"node": "Query Stats", "type": "main", "index": 0}]]},
        "Query Stats": {"main": [[{"node": "Format Stats", "type": "main", "index": 0}]]},
        "Log Webhook": {"main": [[{"node": "Calculate Cost (Webhook)", "type": "main", "index": 0}]]},
        "Calculate Cost (Webhook)": {"main": [[{"node": "Insert Log (Webhook)", "type": "main", "index": 0}]]},
        "Insert Log (Webhook)": {"main": [[{"node": "Respond OK", "type": "main", "index": 0}]]},
    }

    workflow_data = {
        "name": "API Usage Logger",
        "nodes": nodes,
        "connections": connections,
        "settings": {
            "executionOrder": "v1",
        },
    }

    if wf_id:
        print(f"Updating existing workflow {wf_id}...")
        result = api("PUT", f"/workflows/{wf_id}", workflow_data)
    else:
        print("Creating new workflow...")
        result = api("POST", "/workflows", workflow_data)
        wf_id = result.get("id")

    if wf_id:
        # Activate
        api("PUT", f"/workflows/{wf_id}/activate", {})
        print(f"✅ API Usage Logger workflow ready: {wf_id}")
        print(f"   Log webhook: POST {N8N_URL}/webhook/log-api-usage")
        print(f"   Query webhook: GET {N8N_URL}/webhook/api-usage?days=7")

        # Save local snapshot
        full = api("GET", f"/workflows/{wf_id}")
        with open("/home/michael/KiroProject/n8n-workflows/api-usage-logger.json", "w") as f:
            json.dump(full, f, indent=2)
        print("   Saved local snapshot: n8n-workflows/api-usage-logger.json")
    else:
        print("❌ Failed to create/update workflow")
        print(json.dumps(result, indent=2))

    return wf_id


if __name__ == "__main__":
    wf_id = build()
    print(f"\nWorkflow ID: {wf_id}")
    print(f"\nTo add logging to other workflows, add a Code node after each")
    print(f"Anthropic HTTP Request that calls Execute Workflow with this ID.")
