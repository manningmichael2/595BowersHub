#!/usr/bin/env python3
"""
BowersHub AI end-to-end smoke test (Task 31 + bowershub-ai-enhancements 30.3).

Runs against a deployed instance over HTTP/WebSocket and reports
pass/fail per scenario. Not intended as a permanent test suite —
this is a one-shot validator before retiring AnythingLLM and after
deploying enhancements.

Scenarios covered (Task 31 — original chat app):
  A. Health check
  B. Login + JWT issuance
  C. Workspace listing + access
  D. Slash commands list
  E. Conversation create + rename + archive (TODO #29 backend)
  F. /cost slash command (Layer 1 deterministic)
  G. WebSocket connect + auth + send message (Layer 2 or 3 flow)
  H. Skill catalog includes ask-db (TODO #30) and not finance-query
  I. Captured context endpoint reachable

Scenarios covered (bowershub-ai-enhancements task 30.3):
  J. GET /api/themes — returns presets + admin-published + own
  K. GET /api/branding/icon — returns version + urls
  L. GET /api/settings — returns effective_theme + effective_text_size
  M. GET /api/scheduled-prompts — returns the user's scheduled prompts
  N. GET /api/briefing/latest?workspace_id=X — 200 with or without briefing_id
  O. POST /api/quick-capture/raw-note — writes verbatim to /knowledge/captures/

Usage:
    python3 smoke_test.py http://100.106.180.101:5003 admin@example.com password

    # Skip the original Task 31 scenarios (only run enhancement smokes)
    python3 smoke_test.py http://100.106.180.101:5003 admin@example.com password --enhancements-only

    # Skip the WebSocket scenario (e.g., when websocket-client isn't installed)
    python3 smoke_test.py http://100.106.180.101:5003 admin@example.com password --no-ws
"""

import json
import sys
import time
import urllib.request
import urllib.error

try:
    from websocket import create_connection  # websocket-client
except ImportError:
    create_connection = None


class SmokeRunner:
    def __init__(
        self,
        base_url: str,
        email: str,
        password: str,
        *,
        run_original: bool = True,
        run_enhancements: bool = True,
        run_websocket: bool = True,
    ):
        self.base = base_url.rstrip("/")
        self.email = email
        self.password = password
        self.token: str | None = None
        self.results: list[tuple[str, bool, str]] = []
        self.run_original = run_original
        self.run_enhancements = run_enhancements
        self.run_websocket = run_websocket
        self.general_id: int | None = None

    # --- HTTP helpers ---

    def _req(self, method: str, path: str, body: dict | None = None, auth: bool = True) -> tuple[int, dict | str]:
        url = f"{self.base}{path}"
        data = json.dumps(body).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if body is not None else {}
        if auth and self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode()
                code = resp.status
        except urllib.error.HTTPError as e:
            raw = e.read().decode()
            code = e.code
        try:
            return code, json.loads(raw)
        except Exception:
            return code, raw

    def record(self, name: str, ok: bool, detail: str = ""):
        self.results.append((name, ok, detail))
        marker = "✅" if ok else "❌"
        print(f"  {marker} {name}: {detail}")

    # --- Scenarios ---

    def scenario_health(self):
        code, body = self._req("GET", "/api/health", auth=False)
        ok = code == 200 and isinstance(body, dict) and body.get("status") == "ok" and body.get("database") is True
        detail = f"db={body.get('database') if isinstance(body, dict) else 'n/a'} providers={body.get('providers') if isinstance(body, dict) else 'n/a'}"
        self.record("A. Health endpoint", ok, detail)
        return ok

    def scenario_login(self):
        code, body = self._req("POST", "/api/auth/login", {"email": self.email, "password": self.password}, auth=False)
        ok = code == 200 and isinstance(body, dict) and "access_token" in body
        if ok:
            self.token = body["access_token"]
            detail = f"user={body['user']['email']} role={body['user']['role']}"
        else:
            detail = f"code={code} body={body}"
        self.record("B. Login + JWT", ok, detail)
        return ok

    def scenario_workspaces(self) -> int | None:
        code, body = self._req("GET", "/api/workspaces")
        ok = code == 200 and isinstance(body, list) and len(body) > 0
        if ok:
            names = [w.get("name") for w in body]
            detail = f"{len(body)} workspaces: {', '.join(names)}"
            general = next((w for w in body if w.get("name") == "General"), None)
            self.general_id = general["id"] if general else body[0]["id"]
        else:
            self.general_id = None
            detail = f"code={code}"
        self.record("C. Workspace listing", ok, detail)
        return self.general_id

    def scenario_slash_commands(self):
        if not self.general_id:
            self.record("D. Slash commands", False, "skipped (no workspace)")
            return
        code, body = self._req("GET", f"/api/slash-commands?workspace_id={self.general_id}")
        ok = code == 200 and isinstance(body, list)
        commands = [c.get("command") for c in body] if ok else []
        ok = ok and "/help" in commands and "/cost" in commands
        self.record("D. Slash commands list", ok, f"got {len(commands)}: {', '.join(commands[:8])}")

    def scenario_conversation_crud(self):
        if not self.general_id:
            self.record("E. Conversation CRUD", False, "skipped (no workspace)")
            return
        # Create
        code, body = self._req("POST", "/api/conversations", {"workspace_id": self.general_id})
        if code != 200 or not isinstance(body, dict) or "id" not in body:
            self.record("E. Conversation create", False, f"code={code} body={body}")
            return
        conv_id = body["id"]
        # Rename
        code, body = self._req("PATCH", f"/api/conversations/{conv_id}", {"title": "Smoke test conversation"})
        rename_ok = code == 200 and body.get("title") == "Smoke test conversation"
        # Archive
        code, _ = self._req("PATCH", f"/api/conversations/{conv_id}", {"is_archived": True})
        archive_ok = code == 200
        ok = rename_ok and archive_ok
        self.record("E. Conversation create/rename/archive", ok, f"id={conv_id} rename={rename_ok} archive={archive_ok}")

    def scenario_skill_rename(self):
        # Verify ask-db exists and finance-query does not (TODO #30)
        code, body = self._req("GET", "/api/skills")
        if code != 200 or not isinstance(body, list):
            self.record("H. Skill rename (ask-db)", False, f"code={code}")
            return
        names = {s.get("name") for s in body}
        ok = "ask-db" in names and "finance-query" not in names
        self.record("H. Skill rename (ask-db)", ok, f"ask-db present={('ask-db' in names)} finance-query absent={('finance-query' not in names)}")

    def scenario_websocket_chat(self):
        if create_connection is None:
            self.record("G. WebSocket chat", False, "websocket-client not installed (skipped)")
            return
        if not self.general_id or not self.token:
            self.record("G. WebSocket chat", False, "skipped (no auth/workspace)")
            return
        # Need a conversation
        code, body = self._req("POST", "/api/conversations", {"workspace_id": self.general_id})
        if code != 200:
            self.record("G. WebSocket chat", False, f"could not create conversation: {code}")
            return
        conv_id = body["id"]

        ws_url = self.base.replace("http://", "ws://").replace("https://", "wss://") + "/ws/chat"
        try:
            ws = create_connection(ws_url, timeout=15)
            ws.send(json.dumps({"type": "auth", "token": self.token}))
            # Wait for auth_ok or send a simple message
            ws.send(json.dumps({
                "type": "message",
                "conversation_id": conv_id,
                "workspace_id": self.general_id,
                "content": "/help",
            }))
            saw_complete = False
            saw_token_or_layer = False
            t0 = time.time()
            while time.time() - t0 < 20:
                ws.settimeout(5)
                try:
                    raw = ws.recv()
                except Exception:
                    break
                if not raw:
                    break
                try:
                    evt = json.loads(raw)
                except Exception:
                    continue
                t = evt.get("type")
                if t in ("token", "skill_status", "typing"):
                    saw_token_or_layer = True
                if t == "complete":
                    saw_complete = True
                    break
                if t == "error":
                    self.record("G. WebSocket chat", False, f"server error: {evt}")
                    ws.close()
                    return
            ws.close()
            ok = saw_complete or saw_token_or_layer
            self.record("G. WebSocket chat", ok, f"complete={saw_complete} streaming={saw_token_or_layer}")
        except Exception as e:
            self.record("G. WebSocket chat", False, f"exception: {e}")

    def scenario_cost_command(self):
        if not self.general_id:
            self.record("F. /cost layer-1", False, "skipped")
            return
        # Just make sure the slash command lookup succeeds — actual exec goes through WS.
        code, body = self._req("GET", f"/api/slash-commands?workspace_id={self.general_id}")
        ok = code == 200 and any(c.get("command") == "/cost" for c in (body or []))
        self.record("F. /cost slash command registered", ok, "ok" if ok else f"code={code}")

    def scenario_captured_context(self):
        if not self.general_id:
            self.record("I. Captured context", False, "skipped")
            return
        code, body = self._req("GET", f"/api/workspaces/{self.general_id}/captured-context")
        ok = code in (200, 404)
        n = len(body) if isinstance(body, list) else "n/a"
        self.record("I. Captured context endpoint", ok, f"code={code} count={n}")

    # ------------------------------------------------------------------
    # bowershub-ai-enhancements (task 30.3) scenarios
    # ------------------------------------------------------------------

    def scenario_themes_list(self):
        """J. GET /api/themes — visible themes for the user.

        Expects at least the four seeded presets (Dark Navy, Light Stone,
        Forest, Mono) from migration 009. Auth required (R1.2).
        """
        code, body = self._req("GET", "/api/themes")
        ok = code == 200 and isinstance(body, list) and len(body) >= 4
        if ok:
            preset_names = {t.get("name") for t in body if t.get("is_preset")}
            expected = {"Dark Navy", "Light Stone", "Forest", "Mono"}
            preset_ok = expected.issubset(preset_names)
            ok = ok and preset_ok
            detail = f"{len(body)} themes; presets={sorted(preset_names)}"
        else:
            detail = f"code={code} body={body}"
        self.record("J. GET /api/themes", ok, detail)

    def scenario_branding_icon(self):
        """K. GET /api/branding/icon — current manifest.

        Expects {version, urls, has_rollback}. Auth required (R2.1).
        """
        code, body = self._req("GET", "/api/branding/icon")
        ok = (
            code == 200
            and isinstance(body, dict)
            and "version" in body
            and "urls" in body
            and "has_rollback" in body
        )
        if ok:
            url_keys = list(body.get("urls") or {})
            detail = f"version={body['version']} urls={url_keys} has_rollback={body['has_rollback']}"
        else:
            detail = f"code={code} body={body}"
        self.record("K. GET /api/branding/icon", ok, detail)

    def scenario_settings(self):
        """L. GET /api/settings — settings + resolved effects.

        Expects {settings, effective_theme, effective_text_size}. Auth
        required (R3.2). effective_text_size defaults to 'medium' when
        unset (R4.6).
        """
        code, body = self._req("GET", "/api/settings")
        ok = (
            code == 200
            and isinstance(body, dict)
            and "settings" in body
            and "effective_theme" in body
            and "effective_text_size" in body
        )
        if ok:
            theme = body.get("effective_theme") or {}
            detail = (
                f"theme={theme.get('name')} "
                f"text_size={body['effective_text_size']}"
            )
        else:
            detail = f"code={code} body={body}"
        self.record("L. GET /api/settings", ok, detail)

    def scenario_scheduled_prompts_list(self):
        """M. GET /api/scheduled-prompts — list (may be empty).

        Auth required. Filters to the user's accessible workspaces
        (R11.10). An empty list is a valid response.
        """
        code, body = self._req("GET", "/api/scheduled-prompts")
        ok = code == 200 and isinstance(body, list)
        if ok:
            detail = f"{len(body)} scheduled prompts"
        else:
            detail = f"code={code} body={body}"
        self.record("M. GET /api/scheduled-prompts", ok, detail)

    def scenario_briefing_latest(self):
        """N. GET /api/briefing/latest?workspace_id=X — 200 either way.

        With or without a briefing in the last 24h the endpoint returns
        200; absent briefings come back as ``{briefing_id: null}`` (R8.3).
        """
        if not self.general_id:
            self.record("N. GET /api/briefing/latest", False, "skipped (no workspace)")
            return
        code, body = self._req("GET", f"/api/briefing/latest?workspace_id={self.general_id}")
        ok = code == 200 and isinstance(body, dict) and "briefing_id" in body
        if ok:
            bid = body.get("briefing_id")
            if bid is None:
                detail = "no briefing in last 24h (briefing_id=null)"
            else:
                detail = f"briefing_id={bid} age_hours={body.get('age_hours')}"
        else:
            detail = f"code={code} body={body}"
        self.record("N. GET /api/briefing/latest", ok, detail)

    def scenario_quick_capture_raw_note(self):
        """O. POST /api/quick-capture/raw-note — fallback path.

        R9.9 fallback that bypasses the AI pipeline. Writes verbatim to
        ``/knowledge/captures/<slug>.md``. Returns ``{ok, path, topic}``.
        Uses a unique marker in the body so re-runs don't collide on
        slug, but the slug check itself is exercised.
        """
        if not self.general_id:
            self.record("O. POST /api/quick-capture/raw-note", False, "skipped (no workspace)")
            return
        marker = f"smoke-test-{int(time.time())}"
        body_text = (
            f"Smoke test raw note {marker}\n"
            "This is a verbatim capture written by scripts/smoke_test.py."
        )
        code, body = self._req(
            "POST",
            "/api/quick-capture/raw-note",
            {"text": body_text, "workspace_id": self.general_id},
        )
        ok = (
            code == 200
            and isinstance(body, dict)
            and body.get("ok") is True
            and isinstance(body.get("path"), str)
            and body["path"].startswith("/knowledge/captures/")
        )
        if ok:
            detail = f"path={body['path']}"
        else:
            detail = f"code={code} body={body}"
        self.record("O. POST /api/quick-capture/raw-note", ok, detail)

    def run(self):
        print(f"Running smoke test against {self.base}")
        if not self.scenario_health():
            print("Health check failed; aborting.")
            return self.summary()
        if not self.scenario_login():
            print("Login failed; aborting.")
            return self.summary()
        # Workspaces is needed by both halves to look up self.general_id.
        self.scenario_workspaces()

        if self.run_original:
            self.scenario_slash_commands()
            self.scenario_conversation_crud()
            self.scenario_skill_rename()
            self.scenario_cost_command()
            if self.run_websocket:
                self.scenario_websocket_chat()
            self.scenario_captured_context()

        if self.run_enhancements:
            self.scenario_themes_list()
            self.scenario_branding_icon()
            self.scenario_settings()
            self.scenario_scheduled_prompts_list()
            self.scenario_briefing_latest()
            self.scenario_quick_capture_raw_note()

        return self.summary()

    def summary(self):
        passed = sum(1 for _, ok, _ in self.results if ok)
        total = len(self.results)
        print(f"\n=== {passed}/{total} passed ===")
        return 0 if passed == total else 1


if __name__ == "__main__":
    args = sys.argv[1:]
    flags = {a for a in args if a.startswith("--")}
    positional = [a for a in args if not a.startswith("--")]

    if len(positional) < 3:
        print(
            "usage: smoke_test.py BASE_URL EMAIL PASSWORD "
            "[--enhancements-only] [--original-only] [--no-ws]"
        )
        sys.exit(2)

    run_original = "--enhancements-only" not in flags
    run_enhancements = "--original-only" not in flags
    run_websocket = "--no-ws" not in flags

    runner = SmokeRunner(
        positional[0],
        positional[1],
        positional[2],
        run_original=run_original,
        run_enhancements=run_enhancements,
        run_websocket=run_websocket,
    )
    sys.exit(runner.run())
