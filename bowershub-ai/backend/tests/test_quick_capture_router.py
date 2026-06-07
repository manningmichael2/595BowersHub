"""
Integration tests for the quick_capture router (`/api/quick-capture/*`).

The router is a thin pass-through over ``SkillExecutor.execute`` plus a
file-write fallback (R9.9), so the tests exercise the HTTP surface
end-to-end with the executor mocked at the class level. No DB or n8n
connection is required:

  * ``SkillExecutor.execute`` is monkeypatched to return canned smart-
    capture extract / commit responses (and to raise on demand for the
    upstream-failure case).
  * ``get_current_user`` is overridden via FastAPI's ``dependency_overrides``
    so requests skip JWT validation and the user-row DB lookup.
  * ``tmp_path`` is plumbed in as ``KNOWLEDGE_ROOT`` so the raw-note path
    writes onto an isolated on-disk root.

Coverage (per task 14.2):
  - Happy path: extract returns the canned ``{intents, ...}`` shape
    untouched and the executor sees the forwarded params (R9.2).
  - Happy path: commit is called once per accepted intent and returns
    the canned commit response per call (R9.4).
  - Extract upstream failure → HTTP 502 with ``retryable=true`` so the
    overlay can offer Retry + raw-note fallback (R9.9).
  - Raw-note → markdown file written under ``/knowledge/captures/``
    with the user's text preserved verbatim (R9.9 explicit fallback).

Validates: Requirements R9.2, R9.4, R9.9
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.config import Config
from backend.middleware.auth import get_current_user
from backend.routers.quick_capture import router as quick_capture_router
from backend.services import skill_executor as skill_executor_module


# ---------------------------------------------------------------------------
# Fake user + canned upstream payloads
# ---------------------------------------------------------------------------


_FAKE_USER = {
    "id": 42,
    "email": "tester@example.local",
    "display_name": "Tester",
    "role": "member",
    "is_active": True,
}


# Shape mirrors what the n8n smart-capture/extract webhook returns: a
# top-level ``ok`` flag, a list of draft intents, an optional asset, the
# raw input text, and the timestamp-signed ``extract_token`` that the
# matching commit call must echo back.
_EXTRACT_RESPONSE: dict[str, Any] = {
    "ok": True,
    "intents": [
        {
            "domain": "knowledge_fact",
            "summary": "Festool TS 60 blade arrived today",
            "payload": {
                "topic": "woodshop/saw-blades",
                "fact": "Festool TS 60 28T crosscut blade arrived",
            },
            "needs_more_info": False,
        },
        {
            "domain": "shopping_list",
            "summary": "Buy push sticks",
            "payload": {"item": "push sticks", "qty": 2},
            "needs_more_info": False,
        },
    ],
    "asset": None,
    "raw_text": "blade arrived; need push sticks",
    "extract_token": "tok-abc123",
}


_COMMIT_RESPONSE: dict[str, Any] = {
    "ok": True,
    "target": "markdown",
    "path": "/knowledge/woodshop/saw-blades.md",
    "summary": "Saved knowledge fact",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_app(knowledge_root: Path) -> FastAPI:
    """Build a minimal FastAPI app exposing only the quick_capture router.

    Skips the project's lifespan (no DB pool, no model provider, no
    hook engine). The router only touches ``request.app.state.config``,
    ``SkillExecutor.execute``, and ``FileManager.append_knowledge``;
    none of those need anything outside the per-request context once
    the executor is mocked and ``KNOWLEDGE_ROOT`` is pointed at a
    tmp dir.
    """
    app = FastAPI()
    app.include_router(quick_capture_router)

    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST="localhost",
        DB_PORT=5432,
        DB_NAME="postgres",
        DB_USER="test",
        DB_PASSWORD="test",
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
        FILES_ROOT=str(knowledge_root),
        KNOWLEDGE_ROOT=str(knowledge_root),
    )
    app.state.config = config

    async def _override_get_current_user() -> dict:
        return _FAKE_USER

    app.dependency_overrides[get_current_user] = _override_get_current_user
    return app


@pytest.fixture
def app(tmp_path: Path) -> FastAPI:
    return _build_app(tmp_path)


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _make_skill_result(raw_data: Any) -> skill_executor_module.SkillResult:
    """Build a SkillResult equivalent to what SkillExecutor.execute would
    return on a successful webhook call."""
    return skill_executor_module.SkillResult(
        skill_name="smart-capture",
        raw_data=raw_data,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extract_happy_path_returns_intents_shape(client, monkeypatch):
    """``POST /api/quick-capture/extract`` returns the canned smart-
    capture extract payload unchanged and forwards the request params
    to ``smart-capture-extract``.

    Validates: R9.2 (extract pass-through to smart-capture-extract).
    """
    captured_calls: list[tuple[str, dict[str, Any]]] = []

    async def fake_execute(
        self,
        skill_name,
        params,
        user_id,
        workspace_id,
        bypass_workspace_check=False,
    ):
        captured_calls.append((skill_name, dict(params)))
        return _make_skill_result(_EXTRACT_RESPONSE)

    monkeypatch.setattr(
        skill_executor_module.SkillExecutor, "execute", fake_execute
    )

    body = {
        "text": "blade arrived; need push sticks",
        "workspace_id": 7,
        "domain_hint": "shopping",
    }
    response = client.post("/api/quick-capture/extract", json=body)

    assert response.status_code == 200, response.text
    data = response.json()
    # Full payload comes through untouched — including the extract_token
    # the overlay needs for the follow-up commit calls.
    assert data == _EXTRACT_RESPONSE
    assert data["intents"] == _EXTRACT_RESPONSE["intents"]
    assert data["extract_token"] == "tok-abc123"

    # The router routed exactly one call to smart-capture-extract with
    # the body fields forwarded.
    assert len(captured_calls) == 1, captured_calls
    skill_name, params = captured_calls[0]
    assert skill_name == "smart-capture-extract"
    assert params == {
        "text": "blade arrived; need push sticks",
        "domain_hint": "shopping",
    }


def test_commit_called_per_accepted_intent(client, monkeypatch):
    """The full overlay flow is one extract followed by one commit per
    accepted intent. Each commit call should hit the
    ``smart-capture-commit`` skill with the intent's domain + payload
    and the extract_token forwarded verbatim, and the response should
    flow back to the caller unchanged.

    Validates: R9.4 (commit pass-through, called per accepted intent).
    """
    commit_calls: list[dict[str, Any]] = []

    async def fake_execute(
        self,
        skill_name,
        params,
        user_id,
        workspace_id,
        bypass_workspace_check=False,
    ):
        if skill_name == "smart-capture-extract":
            return _make_skill_result(_EXTRACT_RESPONSE)
        if skill_name == "smart-capture-commit":
            commit_calls.append(dict(params))
            return _make_skill_result(_COMMIT_RESPONSE)
        raise AssertionError(f"unexpected skill called: {skill_name}")

    monkeypatch.setattr(
        skill_executor_module.SkillExecutor, "execute", fake_execute
    )

    # Step 1: extract.
    extract_resp = client.post(
        "/api/quick-capture/extract",
        json={"text": "two intents", "workspace_id": 7},
    )
    assert extract_resp.status_code == 200, extract_resp.text
    intents = extract_resp.json()["intents"]
    extract_token = extract_resp.json()["extract_token"]
    assert len(intents) == 2

    # Step 2: commit each accepted intent.
    for intent in intents:
        commit_resp = client.post(
            "/api/quick-capture/commit",
            json={
                "domain": intent["domain"],
                "payload": intent["payload"],
                "extract_token": extract_token,
                "workspace_id": 7,
            },
        )
        assert commit_resp.status_code == 200, commit_resp.text
        # Commit response flows back unchanged.
        assert commit_resp.json() == _COMMIT_RESPONSE

    # One commit call per accepted intent, with domain + payload
    # forwarded and the extract_token echoed.
    assert len(commit_calls) == 2, commit_calls
    assert [c["domain"] for c in commit_calls] == [
        "knowledge_fact",
        "shopping_list",
    ]
    assert [c["payload"] for c in commit_calls] == [
        intents[0]["payload"],
        intents[1]["payload"],
    ]
    assert all(c["extract_token"] == "tok-abc123" for c in commit_calls), (
        "extract_token must be forwarded verbatim — n8n validates the "
        "timestamp signature, the router does not duplicate that check"
    )
    # Source tag is set so smart-capture commit logs can distinguish
    # quick-capture writes from agent-driven writes.
    assert all(c.get("source") == "quick-capture" for c in commit_calls)


def test_extract_upstream_failure_returns_502_with_retryable(
    client, monkeypatch
):
    """When ``SkillExecutor.execute`` raises ``SkillExecutionError`` (n8n
    down, smart-capture webhook 5xx, etc.) the router must surface HTTP
    502 with ``retryable=true`` so the overlay can offer Retry and the
    raw-note fallback (R9.9).

    Validates: R9.9 (upstream-failure surface that drives the fallback).
    """
    async def fake_execute(self, *args, **kwargs):
        raise skill_executor_module.SkillExecutionError(
            "smart-capture-extract",
            status_code=503,
            detail="n8n unreachable",
        )

    monkeypatch.setattr(
        skill_executor_module.SkillExecutor, "execute", fake_execute
    )

    response = client.post(
        "/api/quick-capture/extract",
        json={"text": "anything", "workspace_id": 7},
    )

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert detail["error"] == "smart_capture_unavailable"
    assert detail["retryable"] is True, (
        "retryable flag drives the overlay's Retry + raw-note fallback "
        "branch — must be present on every upstream failure"
    )
    assert detail["upstream_status"] == 503
    assert detail["skill"] == "smart-capture-extract"


def test_raw_note_writes_markdown_under_knowledge_captures(
    client, tmp_path
):
    """``POST /api/quick-capture/raw-note`` writes the body verbatim to
    ``$KNOWLEDGE_ROOT/captures/<slug>.md``, bypassing the AI pipeline.

    The file must:
      - Live under the ``captures/`` directory of KNOWLEDGE_ROOT.
      - Contain every line of the user's text verbatim (raw-note
        promise — R9.9).
      - Carry the explicit raw-note fallback marker so a later reader
        knows the note skipped the AI path.

    Validates: R9.9 (raw-note fallback path).
    """
    text = (
        "TODO buy push sticks for the saw\n"
        "Also pick up new dust collector hose"
    )

    response = client.post(
        "/api/quick-capture/raw-note",
        json={"text": text, "workspace_id": 7},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True

    # Path is reported relative to the knowledge mount (``/knowledge/...``)
    # and lives under captures/.
    assert body["path"].startswith("/knowledge/captures/"), body["path"]
    assert body["path"].endswith(".md"), body["path"]
    assert body["topic"].startswith("captures/")

    # Same file exists on disk under tmp_path/captures/.
    rel = body["path"][len("/knowledge/"):]
    file_on_disk: Path = tmp_path / rel
    assert file_on_disk.is_file(), (
        f"raw-note file not written to {file_on_disk}; tmp_path tree:\n"
        + "\n".join(str(p) for p in tmp_path.rglob("*"))
    )

    contents = file_on_disk.read_text()
    # Verbatim preservation of the user's text (R9.9 — raw-note skips
    # extraction entirely so every line must round-trip).
    assert "TODO buy push sticks for the saw" in contents
    assert "Also pick up new dust collector hose" in contents
    # Explicit fallback marker so the note is identifiable as a raw
    # capture rather than an AI-extracted entry.
    assert "Quick Capture (raw-note fallback)" in contents
