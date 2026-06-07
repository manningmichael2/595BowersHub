"""Create a simple webhook-triggered workflow that invokes the Categorizer.
This lets us trigger batch categorization from curl."""
import json
import subprocess
import sys

from _config import API_KEY, N8N_URL
CATEGORIZER_ID = "onU76wM0FSSeMJ9h"

workflow = {
    "name": "Categorize Now",
    "description": "Webhook that triggers the Categorizer on-demand",
    "nodes": [
        {
            "parameters": {"path": "categorize-now", "httpMethod": "POST", "responseMode": "lastNode", "options": {}},
            "id": "webhook-cn", "name": "Webhook",
            "type": "n8n-nodes-base.webhook", "typeVersion": 2.1,
            "position": [200, 300], "webhookId": "categorize-now-webhook"
        },
        {
            "parameters": {
                "workflowId": {"__rl": True, "mode": "list", "value": CATEGORIZER_ID},
                "workflowInputs": {"value": {"trigger": "manual"}, "mappingMode": "defineBelow", "matchingColumns": [], "schema": [], "attemptToConvertTypes": False, "convertFieldsToString": False},
                "options": {}
            },
            "id": "exec-cat", "name": "Run Categorizer",
            "type": "n8n-nodes-base.executeWorkflow", "typeVersion": 1.2,
            "position": [420, 300]
        },
        {
            "parameters": {"jsCode": "return [{ json: { success: true, triggered_at: new Date().toISOString() } }];"},
            "id": "done-cn", "name": "Done",
            "type": "n8n-nodes-base.code", "typeVersion": 2, "position": [640, 300]
        }
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "Run Categorizer", "type": "main", "index": 0}]]},
        "Run Categorizer": {"main": [[{"node": "Done", "type": "main", "index": 0}]]}
    },
    "settings": {"executionOrder": "v1"}
}

with open('/home/michael/KiroProject/n8n-workflows/categorize-now.json', 'w') as f:
    json.dump(workflow, f, indent=2)

def api(method, path, data=None):
    cmd = ['curl', '-s', '-X', method, '-H', f'X-N8N-API-KEY: {API_KEY}', '-H', 'Content-Type: application/json']
    if data is not None:
        cmd.extend(['-d', json.dumps(data)])
    cmd.append(f'{N8N_URL}/api/v1{path}')
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout) if r.stdout else {}

payload = {k: workflow[k] for k in ['name', 'nodes', 'connections', 'settings']}
resp = api('POST', '/workflows', payload)
wf_id = resp.get('id')
print(f"Created: {wf_id}")
if wf_id:
    act = api('POST', f'/workflows/{wf_id}/activate')
    print(f"Active: {act.get('active')}")
