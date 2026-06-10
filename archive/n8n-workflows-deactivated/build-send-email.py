"""
Build the 'Send Email' n8n workflow.

Single webhook:
  POST /webhook/send-email
       Inputs:  { to, subject, body, is_html? }
       Output:  { ok, to, subject, message }

Uses the Gmail SMTP credential (App Password) already configured in n8n.

Idempotent — safe to re-run.
"""
import json
import subprocess
import sys

from _config import API_KEY, N8N_URL
SMTP_CRED_ID = "vWKbaWIVwEZEzFaD"

validate_code = r"""
const body = $input.first().json.body || $input.first().json;
const to = (body.to || "").trim();
const subject = (body.subject || "").trim();
const emailBody = (body.body || "").trim();
const isHtml = body.is_html === true || body.is_html === "true";

if (!to) throw new Error("Missing 'to' (recipient email address).");
if (!subject) throw new Error("Missing 'subject'.");
if (!emailBody) throw new Error("Missing 'body'.");
if (!to.includes("@")) throw new Error(`Invalid email address: ${to}`);

return [{
  json: { to, subject, body: emailBody, is_html: isHtml }
}];
"""

format_response_code = r"""
const input = $('Validate').first().json;
return [{
  json: {
    ok: true,
    to: input.to,
    subject: input.subject,
    message: `Email sent to ${input.to}: "${input.subject}"`
  }
}];
"""

smtp_creds = {"smtp": {"id": SMTP_CRED_ID, "name": "Gmail SMTP (App Password)"}}

workflow = {
    "name": "Send Email",
    "nodes": [
        {
            "parameters": {
                "path": "send-email",
                "httpMethod": "POST",
                "responseMode": "lastNode",
                "options": {},
            },
            "id": "n-wh",
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [200, 300],
            "webhookId": "send-email",
        },
        {
            "parameters": {"jsCode": validate_code},
            "id": "n-validate",
            "name": "Validate",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 300],
        },
        {
            "parameters": {
                "fromEmail": "manningmichael2@gmail.com",
                "toEmail": "={{ $json.to }}",
                "subject": "={{ $json.subject }}",
                "emailType": "={{ $json.is_html ? 'html' : 'text' }}",
                "message": "={{ $json.body }}",
                "options": {},
            },
            "id": "n-send",
            "name": "Send Email",
            "type": "n8n-nodes-base.sendEmail",
            "typeVersion": 1,
            "position": [600, 300],
            "credentials": smtp_creds,
        },
        {
            "parameters": {"jsCode": format_response_code},
            "id": "n-format",
            "name": "Format Response",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [800, 300],
        },
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "Validate", "type": "main", "index": 0}]]},
        "Validate": {"main": [[{"node": "Send Email", "type": "main", "index": 0}]]},
        "Send Email": {"main": [[{"node": "Format Response", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}


def api(method, path, data=None):
    cmd = [
        "curl", "-s", "-X", method,
        f"{N8N_URL}/api/v1{path}",
        "-H", f"X-N8N-API-KEY: {API_KEY}",
        "-H", "Content-Type: application/json",
    ]
    if data:
        cmd += ["-d", json.dumps(data)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"curl failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout) if result.stdout else {}


def find_workflow_by_name(name):
    resp = api("GET", "/workflows?limit=100")
    for wf in resp.get("data", []):
        if wf["name"] == name:
            return wf["id"]
    return None


def main():
    name = workflow["name"]
    existing_id = find_workflow_by_name(name)

    if existing_id:
        print(f"Found existing workflow '{name}' (id={existing_id}). Updating...")
        resp = api("PUT", f"/workflows/{existing_id}", workflow)
        if "id" not in resp:
            print(f"ERROR: {json.dumps(resp, indent=2)}", file=sys.stderr)
            sys.exit(1)
        wf_id = resp["id"]
        api("POST", f"/workflows/{wf_id}/activate")
        print(f"Updated and activated: {wf_id}")
    else:
        print(f"Creating new workflow '{name}'...")
        resp = api("POST", "/workflows", workflow)
        if "id" not in resp:
            print(f"ERROR: {json.dumps(resp, indent=2)}", file=sys.stderr)
            sys.exit(1)
        wf_id = resp["id"]
        api("POST", f"/workflows/{wf_id}/activate")
        print(f"Created and activated: {wf_id}")

    print(f"\nWebhook: POST {N8N_URL}/webhook/send-email")
    print("Done.")


if __name__ == "__main__":
    main()
