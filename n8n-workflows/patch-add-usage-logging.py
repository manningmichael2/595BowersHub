"""
Patch existing n8n workflows to add API usage logging.

For each workflow that calls Anthropic, this script:
1. Finds the HTTP Request node(s) that call api.anthropic.com
2. Adds an inline Code node after each one that:
   - Fires an async HTTP POST to /webhook/log-api-usage (fire-and-forget)
   - Passes the original response through unchanged

This is idempotent — if logging nodes already exist, they're skipped.

Run AFTER build-api-usage-logger.py has created the logger workflow.
"""
import json
import subprocess
import sys

from _config import API_KEY, N8N_URL

# Workflows that call Anthropic and their node names
WORKFLOWS_TO_PATCH = [
    ("EIinsmGcdxOYqj5c", "Finance SQL Query", "Generate SQL (Haiku)"),
    ("sBenqNOX0E6nOddJ", "Smart Capture", "Classify (Haiku)"),
    ("onU76wM0FSSeMJ9h", "Categorizer", "Call Haiku"),
    ("DeoZgLJCawzgcthm", "Process Asset", "Anthropic Vision"),
    ("9fTh1G0THWgI6XB3", "Knowledge Memory", "Haiku Dedup"),
]


def api(method, path, data=None):
    cmd = ["curl", "-s", "-X", method,
           "-H", f"X-N8N-API-KEY: {API_KEY}",
           "-H", "Content-Type: application/json"]
    if data is not None:
        cmd.extend(["-d", json.dumps(data)])
    cmd.append(f"{N8N_URL}/api/v1{path}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout) if r.stdout.strip() else {}


def find_anthropic_nodes(nodes):
    """Find HTTP Request nodes that call api.anthropic.com."""
    found = []
    for node in nodes:
        if node.get("type") == "n8n-nodes-base.httpRequest":
            params = node.get("parameters", {})
            url = params.get("url", "")
            if "anthropic" in url.lower():
                found.append(node["name"])
    return found


def has_logging_node(nodes, anthropic_node_name):
    """Check if a logging node already exists for this Anthropic node."""
    log_name = f"Log Usage ({anthropic_node_name})"
    return any(n.get("name") == log_name for n in nodes)


def build_log_code(workflow_name, anthropic_node_name):
    """Build the inline passthrough Code node JS."""
    return f'''// Log API usage (fire-and-forget HTTP POST) then pass data through unchanged
const response = $json;
const usage = response.usage || {{}};

const logPayload = {{
  workflow_name: "{workflow_name}",
  node_name: "{anthropic_node_name}",
  model: response.model || "unknown",
  input_tokens: usage.input_tokens || 0,
  output_tokens: usage.output_tokens || 0,
  cache_read_tokens: usage.cache_creation_input_tokens || 0,
  cache_write_tokens: usage.cache_read_input_tokens || 0,
}};

try {{
  await this.helpers.httpRequest({{
    method: "POST",
    url: "http://100.106.180.101:5678/webhook/log-api-usage",
    body: logPayload,
    json: true,
    timeout: 3000,
  }});
}} catch (e) {{
  // Logging failure should never break the main workflow
}}

// Pass through the original response unchanged
return [{{ json: response }}];'''


def patch_workflow(wf_id, workflow_name, anthropic_node_name):
    """Add an inline logging Code node after the Anthropic HTTP Request node."""
    print(f"\n--- Patching: {workflow_name} ({wf_id}) ---")

    wf = api("GET", f"/workflows/{wf_id}")
    if not wf or "nodes" not in wf:
        print(f"  ❌ Could not fetch workflow")
        return False

    nodes = wf["nodes"]
    connections = wf["connections"]

    # If no specific node name given, discover it
    if not anthropic_node_name:
        found = find_anthropic_nodes(nodes)
        if not found:
            print(f"  ⚠️  No Anthropic HTTP Request nodes found, skipping")
            return False
        anthropic_node_name = found[0]
        print(f"  Found Anthropic node: '{anthropic_node_name}'")

    # Check if already patched
    if has_logging_node(nodes, anthropic_node_name):
        print(f"  ✅ Already has logging node, skipping")
        return True

    # Find the Anthropic node and its position
    anthropic_node = None
    for n in nodes:
        if n.get("name") == anthropic_node_name:
            anthropic_node = n
            break

    if not anthropic_node:
        print(f"  ❌ Node '{anthropic_node_name}' not found in workflow")
        return False

    position = anthropic_node.get("position", [400, 300])
    log_node_name = f"Log Usage ({anthropic_node_name})"

    # Find what the Anthropic node currently connects to
    downstream = connections.get(anthropic_node_name, {}).get("main", [[]])[0]

    # Create the inline logging Code node
    code_node = {
        "name": log_node_name,
        "type": "n8n-nodes-base.code",
        "typeVersion": 2,
        "position": [position[0] + 50, position[1] + 120],
        "parameters": {
            "jsCode": build_log_code(workflow_name, anthropic_node_name),
        },
    }

    nodes.append(code_node)

    # Rewire: Anthropic → Log Usage → original downstream
    connections[anthropic_node_name] = {
        "main": [[{"node": log_node_name, "type": "main", "index": 0}]]
    }
    connections[log_node_name] = {"main": [downstream]}

    # Update the workflow
    result = api("PUT", f"/workflows/{wf_id}", {
        "name": wf.get("name", workflow_name),
        "nodes": nodes,
        "connections": connections,
        "settings": wf.get("settings", {"executionOrder": "v1"}),
    })

    if result.get("id"):
        print(f"  ✅ Patched successfully")
        return True
    else:
        print(f"  ❌ Update failed: {json.dumps(result, indent=2)[:200]}")
        return False


def main():
    print("API Usage Logging Patcher")
    print("=" * 50)

    success = 0
    failed = 0
    for wf_id, wf_name, node_name in WORKFLOWS_TO_PATCH:
        if patch_workflow(wf_id, wf_name, node_name):
            success += 1
        else:
            failed += 1

    print(f"\n{'='*50}")
    print(f"Done. Patched: {success}, Failed/Skipped: {failed}")
    print(f"\nUsage data flows into public.api_usage_log")
    print(f"Query: GET {N8N_URL}/webhook/api-usage?days=7")


if __name__ == "__main__":
    main()
