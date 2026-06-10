#!/usr/bin/env python3
"""Inspect the SimpleFin workflow's date-handling and transform nodes."""
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


wf = get(f"/workflows/{SIMPLEFIN_ID}")
nodes = wf.get('nodes', [])

# Look at the date-related nodes and HTTP request to SimpleFin
for node in nodes:
    name = node['name']
    ntype = node['type']
    params = node.get('parameters', {})
    
    if any(kw in name.lower() for kw in ['date', 'simplefin', 'transform', 'http', 'request']):
        print(f"\n=== {name} ({ntype}) ===")
        # Print parameters but truncate code
        params_str = json.dumps(params, indent=2)
        if len(params_str) > 1500:
            params_str = params_str[:1500] + "\n... (truncated)"
        print(params_str)

# Also look at the most recent execution's actual SimpleFin response
print("\n\n=== Most recent execution: SimpleFin HTTP response ===")
execs = get(f"/executions?workflowId={SIMPLEFIN_ID}&limit=1&includeData=true").get("data", [])
if execs:
    ex = execs[0]
    run_data = ex.get("data", {}).get("resultData", {}).get("runData", {})
    for node_name, runs in run_data.items():
        if 'http' in node_name.lower() or 'simplefin' in node_name.lower():
            run = runs[0]
            output = run.get("data", {}).get("main", [[]])
            if output and len(output) > 0 and output[0]:
                item = output[0][0].get("json", {})
                print(f"\n{node_name}:")
                # Show top-level keys
                if isinstance(item, dict):
                    for k, v in item.items():
                        if isinstance(v, list):
                            print(f"  {k}: list with {len(v)} items")
                            if k == "transactions" and v:
                                print(f"    First 2 transactions:")
                                for t in v[:2]:
                                    print(f"      {json.dumps(t)[:200]}")
                        elif isinstance(v, dict):
                            print(f"  {k}: dict with {len(v)} keys")
                        else:
                            print(f"  {k}: {str(v)[:80]}")
                else:
                    print(f"  {str(item)[:300]}")
