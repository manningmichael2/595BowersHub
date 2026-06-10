import os
#!/usr/bin/env python3
"""
Wire the "Run Categorizer" Execute Sub-Workflow node into the
Historical Load (Postgres) workflow.

Flow: ... → Update House Tags → Run Categorizer → IF DUAL_WRITE Enabled → ...
"""

import json
import requests

BASE_URL = "http://100.106.180.101:5678/api/v1"
API_KEY = os.environ.get("N8N_API_KEY", "")  # ROTATED — set via env var
WORKFLOW_ID = "1BcxrSvq0MXRQut6"
CATEGORIZER_WORKFLOW_ID = "onU76wM0FSSeMJ9h"

headers = {
    "X-N8N-API-KEY": API_KEY,
    "Content-Type": "application/json",
}


def main():
    # 1. GET the current workflow
    print(f"[1] Fetching workflow {WORKFLOW_ID}...")
    resp = requests.get(f"{BASE_URL}/workflows/{WORKFLOW_ID}", headers=headers)
    resp.raise_for_status()
    workflow = resp.json()
    print(f"    Workflow name: {workflow['name']}")

    nodes = workflow["nodes"]
    connections = workflow["connections"]

    # Find the "Update House Tags" node and "IF DUAL_WRITE Enabled" node
    update_house_tags_node = None
    if_dual_write_node = None

    for node in nodes:
        if node["name"] == "Update House Tags":
            update_house_tags_node = node
        elif node["name"] == "IF DUAL_WRITE Enabled":
            if_dual_write_node = node

    if not update_house_tags_node:
        print("ERROR: Could not find 'Update House Tags' node!")
        return
    if not if_dual_write_node:
        print("ERROR: Could not find 'IF DUAL_WRITE Enabled' node!")
        return

    print(f"    Found 'Update House Tags' at position {update_house_tags_node.get('position')}")
    print(f"    Found 'IF DUAL_WRITE Enabled' at position {if_dual_write_node.get('position')}")

    # 2. Create the "Run Categorizer" node
    # Position it between the two nodes
    uht_pos = update_house_tags_node.get("position", [0, 0])
    ifdw_pos = if_dual_write_node.get("position", [0, 0])
    new_x = (uht_pos[0] + ifdw_pos[0]) // 2
    new_y = (uht_pos[1] + ifdw_pos[1]) // 2

    run_categorizer_node = {
        "parameters": {
            "source": "database",
            "workflowId": CATEGORIZER_WORKFLOW_ID,
        },
        "name": "Run Categorizer",
        "type": "n8n-nodes-base.executeWorkflow",
        "typeVersion": 1.2,
        "position": [new_x, new_y],
    }

    # Check if "Run Categorizer" already exists
    existing = [n for n in nodes if n["name"] == "Run Categorizer"]
    if existing:
        print("    'Run Categorizer' node already exists — removing old one first.")
        nodes = [n for n in nodes if n["name"] != "Run Categorizer"]
        # Also clean up any connections referencing it
        connections.pop("Run Categorizer", None)

    nodes.append(run_categorizer_node)
    print(f"    Added 'Run Categorizer' node at position [{new_x}, {new_y}]")

    # 3. Update connections
    # Remove the connection from "Update House Tags" → "IF DUAL_WRITE Enabled"
    # and replace with:
    #   "Update House Tags" → "Run Categorizer"
    #   "Run Categorizer" → "IF DUAL_WRITE Enabled"

    uht_connections = connections.get("Update House Tags", {})
    # Find and remove the connection to "IF DUAL_WRITE Enabled"
    if "main" in uht_connections:
        for output_idx, output_conns in enumerate(uht_connections["main"]):
            new_conns = []
            for conn in output_conns:
                if conn.get("node") == "IF DUAL_WRITE Enabled":
                    print(f"    Removing direct connection: Update House Tags → IF DUAL_WRITE Enabled")
                else:
                    new_conns.append(conn)
            # Add connection to Run Categorizer
            new_conns.append({
                "node": "Run Categorizer",
                "type": "main",
                "index": 0,
            })
            uht_connections["main"][output_idx] = new_conns
    else:
        # No existing main connections, create one
        uht_connections["main"] = [[{
            "node": "Run Categorizer",
            "type": "main",
            "index": 0,
        }]]

    connections["Update House Tags"] = uht_connections

    # Add connection from "Run Categorizer" → "IF DUAL_WRITE Enabled"
    connections["Run Categorizer"] = {
        "main": [[{
            "node": "IF DUAL_WRITE Enabled",
            "type": "main",
            "index": 0,
        }]]
    }

    print("    Wired: Update House Tags → Run Categorizer → IF DUAL_WRITE Enabled")

    # 4. PUT the updated workflow back
    put_body = {
        "name": workflow["name"],
        "nodes": nodes,
        "connections": connections,
        "settings": {"executionOrder": "v1"},
    }

    print(f"\n[2] Updating workflow {WORKFLOW_ID}...")
    resp = requests.put(
        f"{BASE_URL}/workflows/{WORKFLOW_ID}",
        headers=headers,
        json=put_body,
    )
    resp.raise_for_status()
    result = resp.json()
    print(f"    Success! Workflow '{result['name']}' updated.")
    print(f"    Total nodes: {len(result['nodes'])}")

    # Verify the new node exists
    categorizer_nodes = [n for n in result["nodes"] if n["name"] == "Run Categorizer"]
    if categorizer_nodes:
        print(f"    ✓ 'Run Categorizer' node confirmed in workflow")
    else:
        print(f"    ✗ WARNING: 'Run Categorizer' node NOT found in response!")

    # Verify connections
    result_conns = result.get("connections", {})
    uht_out = result_conns.get("Update House Tags", {}).get("main", [[]])
    rc_out = result_conns.get("Run Categorizer", {}).get("main", [[]])

    uht_targets = [c["node"] for conns in uht_out for c in conns]
    rc_targets = [c["node"] for conns in rc_out for c in conns]

    if "Run Categorizer" in uht_targets:
        print(f"    ✓ Connection verified: Update House Tags → Run Categorizer")
    else:
        print(f"    ✗ WARNING: Missing connection Update House Tags → Run Categorizer")

    if "IF DUAL_WRITE Enabled" in rc_targets:
        print(f"    ✓ Connection verified: Run Categorizer → IF DUAL_WRITE Enabled")
    else:
        print(f"    ✗ WARNING: Missing connection Run Categorizer → IF DUAL_WRITE Enabled")

    print("\nDone!")


if __name__ == "__main__":
    main()
