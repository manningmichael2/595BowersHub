#!/usr/bin/env python3
"""
Quick interactive chat smoke check — sends one real question to the
running BowersHub AI and prints the assistant's reply. Used to spot-check
that L3 routing + tool calls work post-deploy.

Usage:
    python3 smoke_chat.py BASE_URL EMAIL PASSWORD WORKSPACE_NAME "your question"
"""

import json
import sys
import time
import urllib.request

from websocket import create_connection


def login(base, email, password):
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def get_workspaces(base, token):
    req = urllib.request.Request(
        f"{base}/api/workspaces",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def create_conversation(base, token, workspace_id):
    req = urllib.request.Request(
        f"{base}/api/conversations",
        data=json.dumps({"workspace_id": workspace_id}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    if len(sys.argv) < 6:
        print("usage: smoke_chat.py BASE EMAIL PASS WORKSPACE QUESTION")
        sys.exit(2)
    base, email, password, ws_name, question = sys.argv[1:6]
    base = base.rstrip("/")

    auth = login(base, email, password)
    token = auth["access_token"]
    print(f"logged in as {auth['user']['email']}")

    workspaces = get_workspaces(base, token)
    ws = next((w for w in workspaces if w["name"].lower() == ws_name.lower()), None)
    if not ws:
        print(f"workspace not found: {ws_name}")
        sys.exit(1)
    print(f"using workspace: {ws['name']} (id={ws['id']})")

    conv = create_conversation(base, token, ws["id"])
    print(f"conversation: {conv['id']}")

    ws_url = base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/chat"
    sock = create_connection(ws_url, timeout=15)
    sock.send(json.dumps({"type": "auth", "token": token}))
    sock.send(json.dumps({
        "type": "message",
        "conversation_id": conv["id"],
        "workspace_id": ws["id"],
        "content": question,
    }))

    print(f"\n>>> {question}\n")
    print("assistant: ", end="", flush=True)
    started = time.time()
    full = []
    layer = None
    cost = None
    while time.time() - started < 120:
        sock.settimeout(120)
        try:
            raw = sock.recv()
        except Exception as e:
            print(f"\n[recv error: {e}]")
            break
        if not raw:
            break
        try:
            evt = json.loads(raw)
        except Exception:
            continue
        t = evt.get("type")
        if t == "token":
            tok = evt.get("data", "")
            print(tok, end="", flush=True)
            full.append(tok)
        elif t == "skill_status":
            d = evt.get("data", {})
            print(f"\n[tool: {d.get('skill')} {d.get('status')}]", end="", flush=True)
        elif t == "complete":
            d = evt.get("data", {})
            layer = d.get("routing_layer")
            cost = d.get("cost_usd")
            break
        elif t == "error":
            print(f"\n[error: {evt}]")
            break
    sock.close()
    print(f"\n\n--- layer={layer} cost=${cost} ---")


if __name__ == "__main__":
    main()
