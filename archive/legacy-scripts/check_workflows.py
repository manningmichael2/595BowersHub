#!/usr/bin/env python3
"""Check status of all n8n workflows and recent executions."""
import json
import urllib.request
import os
from datetime import datetime, timezone

API_KEY = os.environ["N8N_API_KEY"]
BASE = "http://localhost:5678/api/v1"


def get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={"X-N8N-API-KEY": API_KEY})
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


# Get all workflows
all_wfs = get("/workflows").get("data", [])
active = [w for w in all_wfs if w.get("active")]
inactive = [w for w in all_wfs if not w.get("active")]

print(f"=== Workflows: {len(all_wfs)} total ({len(active)} active, {len(inactive)} inactive) ===\n")

print("ACTIVE:")
for wf in sorted(active, key=lambda w: w["name"]):
    print(f"  [{wf['id']}] {wf['name']}")

print("\nINACTIVE:")
for wf in sorted(inactive, key=lambda w: w["name"]):
    print(f"  [{wf['id']}] {wf['name']}")

# Get recent executions
print("\n=== Recent Executions (last 30) ===")
execs = get("/executions?limit=30").get("data", [])

now = datetime.now(timezone.utc)
print(f"{'When':<14} {'Status':<10} {'Workflow':<40}")
print("-" * 70)
for ex in execs:
    started = ex.get("startedAt", "")
    if started:
        try:
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            ago = (now - dt).total_seconds()
            if ago < 60:
                ago_str = f"{int(ago)}s ago"
            elif ago < 3600:
                ago_str = f"{int(ago/60)}m ago"
            elif ago < 86400:
                ago_str = f"{int(ago/3600)}h ago"
            else:
                ago_str = f"{int(ago/86400)}d ago"
        except Exception:
            ago_str = started[:16]
    else:
        ago_str = "?"
    
    if ex.get("stoppedAt") and not ex.get("finished"):
        status = "FAILED"
    elif ex.get("finished"):
        status = "OK"
    else:
        status = "RUNNING"
    
    name = ex.get("workflowName") or f"id:{ex.get('workflowId', '?')}"
    name = name[:38]
    
    print(f"{ago_str:<14} {status:<10} {name:<40}")
