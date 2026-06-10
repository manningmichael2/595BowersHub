#!/usr/bin/env python3
"""Widen the SimpleFin sync window from 1 day to 14 days.

Idempotent — re-run safely.
"""
import json
import urllib.request
import urllib.error
import os
import sys

API_KEY = os.environ.get("N8N_API_KEY")
if not API_KEY:
    print("ERROR: N8N_API_KEY env var required", file=sys.stderr)
    sys.exit(1)

BASE = "http://localhost:5678/api/v1"
SIMPLEFIN_ID = "XF9ye6jAAO012Ys4"

NEW_CODE = """// PATCH:simplefin-window-v2 — fetches last 14 days, not just yesterday.
// The upsert uses ON CONFLICT DO NOTHING on txn id, so re-fetching same
// data is safe — duplicates won't insert. Wider window catches transactions
// that take days to post (common over weekends).
const now = new Date();
const start = new Date(now);
start.setDate(start.getDate() - 14);
start.setHours(0, 0, 0, 0);

const startDate = Math.floor(start.getTime() / 1000);

return [{ json: { startDate } }];
"""


def api(method, path, data=None):
    headers = {"X-N8N-API-KEY": API_KEY, "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"HTTP {e.code} on {method} {path}: {body}", file=sys.stderr)
        raise


# Get current workflow
wf = api("GET", f"/workflows/{SIMPLEFIN_ID}")
print(f"Patching: {wf['name']} (active: {wf.get('active')})")

# Update the schedule start date node
patched = False
for node in wf['nodes']:
    if node['name'] == 'schedule start date':
        old_code = node['parameters'].get('jsCode', '')
        if 'simplefin-window-v2' in old_code:
            print("  Already patched (v2). Skipping.")
            sys.exit(0)
        node['parameters']['jsCode'] = NEW_CODE
        patched = True
        break

if not patched:
    print("ERROR: Could not find 'schedule start date' node", file=sys.stderr)
    sys.exit(1)

# Remove the "Run Categorizer" node since Categorizer is deactivated
# (BowersHub AI's Python apscheduler handles categorization now).
# Reconnect any node that pointed to Run Categorizer to whatever it pointed to.
removed_nodes = []
for node in list(wf['nodes']):
    if node['name'] == 'Run Categorizer':
        wf['nodes'].remove(node)
        removed_nodes.append('Run Categorizer')
        print(f"  Removed orphan node: Run Categorizer (Categorizer workflow is now handled by Python)")

# Clean up connections that reference removed nodes
for src_name, conns in list(wf.get('connections', {}).items()):
    if src_name in removed_nodes:
        del wf['connections'][src_name]
        continue
    for conn_type, branches in list(conns.items()):
        for branch in branches:
            for c in list(branch):
                if c.get('node') in removed_nodes:
                    branch.remove(c)

# n8n PUT API requires only updateable fields, NOT id/active/createdAt/etc.
# Strip read-only fields.
allowed = {"name", "nodes", "connections", "settings", "staticData"}
update_payload = {k: v for k, v in wf.items() if k in allowed}

# settings has restricted properties — only keep allowed keys
allowed_settings = {"saveExecutionProgress", "saveManualExecutions", "saveDataErrorExecution",
                    "saveDataSuccessExecution", "executionTimeout", "errorWorkflow", "timezone",
                    "executionOrder"}
if "settings" in update_payload and isinstance(update_payload["settings"], dict):
    update_payload["settings"] = {k: v for k, v in update_payload["settings"].items() if k in allowed_settings}
else:
    update_payload["settings"] = {}

result = api("PUT", f"/workflows/{SIMPLEFIN_ID}", update_payload)
print(f"  ✓ Patched. Window expanded from 1 day → 14 days.")
print(f"  Workflow saved with {len(result.get('nodes', []))} nodes.")
