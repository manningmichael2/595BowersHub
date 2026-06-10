#!/usr/bin/env python3
"""Look at the most recent SimpleFin Nightly Sync execution in detail."""
import json
import urllib.request
import os

API_KEY = os.environ["N8N_API_KEY"]
BASE = "http://localhost:5678/api/v1"
SIMPLEFIN_ID = "XF9ye6jAAO012Ys4"


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-N8N-API-KEY": API_KEY})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


# Get most recent execution with full data
execs = get(f"/executions?workflowId={SIMPLEFIN_ID}&limit=1&includeData=true").get("data", [])
if not execs:
    print("No executions found.")
    exit(0)

ex = execs[0]
print(f"Execution ID: {ex['id']}")
print(f"Started: {ex.get('startedAt')}")
print(f"Stopped: {ex.get('stoppedAt')}")
print(f"Status: {'OK' if ex.get('finished') else 'FAILED/RUNNING'}")

# Try to get the run data
data = ex.get("data", {})
result_data = data.get("resultData", {})
run_data = result_data.get("runData", {})

print(f"\nNodes that ran ({len(run_data)}):")
for node_name, runs in run_data.items():
    if not runs:
        continue
    run = runs[0]
    output = run.get("data", {}).get("main", [[]])
    item_count = 0
    if output and len(output) > 0 and output[0]:
        item_count = len(output[0])
    error = run.get("error", {})
    err_msg = ""
    if error:
        err_msg = f" ERROR: {error.get('message', 'unknown')}"
    print(f"  - {node_name}: {item_count} items{err_msg}")

# Look for any errors
if result_data.get("error"):
    print(f"\nWORKFLOW ERROR: {result_data['error']}")

# Look at last_run_data for the Postgres insert if present
for node_name, runs in run_data.items():
    if "postgres" in node_name.lower() or "insert" in node_name.lower() or "transaction" in node_name.lower():
        run = runs[0]
        output = run.get("data", {}).get("main", [[]])
        if output and len(output) > 0:
            print(f"\n{node_name} returned {len(output[0])} items:")
            for item in output[0][:3]:
                json_data = item.get("json", {})
                print(f"  {json.dumps(json_data, indent=2)[:200]}")
