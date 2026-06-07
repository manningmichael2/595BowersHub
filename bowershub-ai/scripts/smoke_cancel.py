#!/usr/bin/env python3
"""
Smoke test for the cancel-streaming feature.
Sends a long-form L3 question, waits for streaming to start, sends cancel, verifies cancellation.
"""
import json, sys, time, urllib.request
from websocket import create_connection


def login(base, email, password):
    req = urllib.request.Request(
        f"{base}/api/auth/login",
        data=json.dumps({"email": email, "password": password}).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def main():
    base, email, password = sys.argv[1:4]
    base = base.rstrip("/")
    auth = login(base, email, password)
    token = auth["access_token"]

    req = urllib.request.Request(
        f"{base}/api/workspaces", headers={"Authorization": f"Bearer {token}"}
    )
    workspaces = json.loads(urllib.request.urlopen(req, timeout=10).read())
    ws = next(w for w in workspaces if w["name"] == "General")

    req = urllib.request.Request(
        f"{base}/api/conversations",
        data=json.dumps({"workspace_id": ws["id"]}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    conv = json.loads(urllib.request.urlopen(req, timeout=10).read())
    conv_id = conv["id"]
    print(f"conv {conv_id}")

    sock = create_connection(base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/chat", timeout=10)
    sock.send(json.dumps({"type": "auth", "token": token}))
    sock.send(json.dumps({
        "type": "message", "conversation_id": conv_id, "workspace_id": ws["id"],
        "content": "Write a 1500-word essay about the history of the woodworking router. Take your time and be thorough.",
    }))

    # Wait until we see streaming activity, then cancel
    cancelled = False
    saw_token = False
    deadline = time.time() + 30
    while time.time() < deadline:
        sock.settimeout(20)
        try:
            raw = sock.recv()
        except Exception as e:
            print(f"recv err: {e}")
            break
        if not raw:
            break
        evt = json.loads(raw)
        t = evt.get("type")
        if t == "token" and not cancelled:
            saw_token = True
            print("[saw token, sending cancel]")
            sock.send(json.dumps({"type": "cancel", "conversation_id": conv_id}))
            cancelled = True
        elif t == "cancelled":
            print(f"[cancelled event: {evt.get('data', {}).get('message')}]")
            break
        elif t == "complete":
            print(f"[complete BEFORE cancel — content length {len(evt.get('data',{}).get('content',''))}]")
            break
        elif t == "error":
            print(f"[error: {evt}]")
            break
    sock.close()
    print("done. saw_token=", saw_token, "cancelled=", cancelled)


if __name__ == "__main__":
    main()
