"""Task 7 — db_browser inbox extract consumers now route through dispatch.

Both /inbox/ai-extract and /inbox/url-extract must (a) go through
SkillExecutor.execute("smart-capture-extract") instead of a raw n8n webhook
POST, (b) preserve the raw extract response shape, (c) url-extract passes the
URL as TEXT (no scrape), and (d) surface a clear error (not silent-empty) on
executor failure. Called directly (no HTTP) with the executor + workspace
resolver mocked — no DB/n8n. (n8n-decommission spec)
"""

from __future__ import annotations

import types

import pytest
from fastapi import HTTPException

from backend.routers import db_browser
from backend.services import skill_executor as se_mod

_FAKE_USER = {"id": 42, "role": "admin"}
_RAW_EXTRACT = {"ok": True, "intents": [{"domain": "tool", "summary": "s", "payload": {}}],
                "asset": None, "raw_text": "r", "extract_token": "tok"}


def _req(body: dict):
    app = types.SimpleNamespace(state=types.SimpleNamespace(
        config=types.SimpleNamespace(N8N_BASE="http://n8n:5678")))

    class _R:
        def __init__(self):
            self.app = app

        async def json(self):
            return body

    return _R()


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    async def _ws(conn, user_id):
        return 5
    monkeypatch.setattr(db_browser, "_resolve_inbox_workspace", _ws)
    # _run_inbox_extract acquires a pool conn for the (patched) resolver; give it
    # a no-op async context manager so no DB is touched.
    class _Conn: ...
    class _Acq:
        async def __aenter__(self): return _Conn()
        async def __aexit__(self, *a): return False
    monkeypatch.setattr(db_browser, "get_pool", lambda: types.SimpleNamespace(acquire=lambda: _Acq()))


@pytest.mark.asyncio
async def test_ai_extract_routes_through_dispatch(monkeypatch):
    calls = []

    async def fake_execute(self, skill_name, params, user_id, workspace_id, bypass_workspace_check=False):
        calls.append((skill_name, params, user_id, workspace_id, bypass_workspace_check))
        return se_mod.SkillResult(skill_name=skill_name, raw_data=_RAW_EXTRACT)

    monkeypatch.setattr(se_mod.SkillExecutor, "execute", fake_execute)

    out = await db_browser.inbox_ai_extract(
        _req({"image_path": "inbox/x.jpg", "domain_hint": "tool"}), user=_FAKE_USER
    )
    assert out == _RAW_EXTRACT  # raw shape preserved
    name, params, uid, wid, bypass = calls[0]
    assert name == "smart-capture-extract"
    assert params == {"image_path": "inbox/x.jpg", "domain_hint": "tool"}
    assert uid == 42 and wid == 5 and bypass is True


@pytest.mark.asyncio
async def test_url_extract_passes_url_as_text_no_scrape(monkeypatch):
    calls = []

    async def fake_execute(self, skill_name, params, user_id, workspace_id, bypass_workspace_check=False):
        calls.append(params)
        return se_mod.SkillResult(skill_name=skill_name, raw_data=_RAW_EXTRACT)

    monkeypatch.setattr(se_mod.SkillExecutor, "execute", fake_execute)

    out = await db_browser.inbox_url_extract(
        _req({"url": "https://example.com/item", "columns": ["price", "brand"]}), user=_FAKE_USER
    )
    assert out == _RAW_EXTRACT
    params = calls[0]
    # URL passed as text (no scraping), columns appended, no image_path.
    assert "https://example.com/item" in params["text"]
    assert "price, brand" in params["text"]
    assert "image_path" not in params


@pytest.mark.asyncio
async def test_inbox_extract_surfaces_error(monkeypatch):
    async def fake_execute(self, *a, **k):
        raise se_mod.SkillExecutionError("smart-capture-extract", status_code=503, detail="n8n down")

    monkeypatch.setattr(se_mod.SkillExecutor, "execute", fake_execute)

    with pytest.raises(HTTPException) as ei:
        await db_browser.inbox_ai_extract(_req({"text": "x"}), user=_FAKE_USER)
    assert ei.value.status_code == 502  # clear error, not silent-empty
