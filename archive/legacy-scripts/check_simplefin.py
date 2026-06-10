#!/usr/bin/env python3
"""Check SimpleFin Nightly Sync execution history."""
import json
import urllib.request
import os
from datetime import datetime, timezone

API_KEY = os.environ["N8N_API_KEY"]
BASE = "http://localhost:5678/api/v1"

SIMPLEFIN_ID = "XF9ye6jAAO012Ys4"


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-N8N-API-KEY": API_KEY})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


# Get executions for SimpleFin Nightly Sync specifically
print(f"=== SimpleFin Nightly Sync executions ===\n")
execs = get(f"/executions?workflowId={SIMPLEFIN_ID}&limit=20").get("data", [])

if not execs:
    print("NO EXECUTIONS FOUND. The workflow has not run.")
else:
    now = datetime.now(timezone.utc)
    for ex in execs:
        started = ex.get("startedAt", "")
        if started:
            try:
                dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
                ago = (now - dt).total_seconds()
                if ago < 86400:
                    ago_str = f"{int(ago/3600)}h ago"
                else:
                    ago_str = f"{int(ago/86400)}d ago"
                date_str = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                date_str = started[:16]
                ago_str = "?"
        else:
            date_str = "?"
            ago_str = "?"
        
        if ex.get("stoppedAt") and not ex.get("finished"):
            status = "FAILED"
        elif ex.get("finished"):
            status = "OK"
        else:
            status = "RUNNING"
        
        print(f"  {date_str} ({ago_str}) — {status}")

# Get full workflow details to check the schedule
print(f"\n=== Workflow config ===")
wf = get(f"/workflows/{SIMPLEFIN_ID}")
print(f"Name: {wf.get('name')}")
print(f"Active: {wf.get('active')}")
nodes = wf.get('nodes', [])
for node in nodes:
    if 'trigger' in node.get('type', '').lower() or 'cron' in node.get('type', '').lower() or 'schedule' in node.get('type', '').lower():
        print(f"\nTrigger node: {node['name']} ({node['type']})")
        params = node.get('parameters', {})
        print(f"Parameters: {json.dumps(params, indent=2)[:500]}")
