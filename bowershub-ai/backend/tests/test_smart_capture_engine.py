"""Task 5 — engine dispatch (native / n8n / shadow) + executor context injection.
(n8n-decommission spec)
"""

from __future__ import annotations

import json
import types

import pytest

from backend.config import Config
from backend.database import close_pool, get_pool
from backend.models.message import CompletionResult
from backend.services.skill_executor import SkillExecutor
from backend.services.skill_registry import native_skill
from backend.services.smart_capture import engine as sc_engine
from backend.services.smart_capture import tokens as sc_tokens
from backend.services.smart_capture.config import get_token_secret
from backend.services.smart_capture.intents import intent_hash
from backend.tests.semantic_helpers import apply_migrations

UID, WID = 7, 3


class FakeProvider:
    async def complete(self, **kwargs):
        content = json.dumps(
            {"intents": [{"domain": "tool", "summary": "s", "payload": {"name": "drill"}}]}
        )
        return CompletionResult(content=content, model="fake", input_tokens=1, output_tokens=1)


async def _set_engine(value: str):
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE public.bh_platform_settings SET value_json=$1::jsonb WHERE key='smart_capture.engine'",
            f'"{value}"',
        )


def _params(**extra):
    base = {
        "_user_id": UID,
        "_workspace_id": WID,
        "_config": types.SimpleNamespace(N8N_BASE="http://n8n:5678"),
        "_model_provider": FakeProvider(),
    }
    base.update(extra)
    return base


async def _fake_proxy(path, body, config):
    return {"ok": True, "intents": [{"domain": "album", "summary": "x", "payload": {}}],
            "asset": None, "raw_text": "r", "extract_token": "n8n-token", "_via": "proxy", "_path": path}


@pytest.mark.asyncio
async def test_native_extract_runs_in_process(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        monkeypatch.setattr(sc_engine, "_proxy_n8n", _fake_proxy)
        await _set_engine("native")
        out = await sc_engine.run_extract(_params(text="a drill"))
        assert out.get("_via") != "proxy"  # native, not proxied
        assert out["ok"] and out["intents"][0]["domain"] == "tool"
        assert out["extract_token"] and "." in out["extract_token"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_n8n_extract_proxies(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        monkeypatch.setattr(sc_engine, "_proxy_n8n", _fake_proxy)
        await _set_engine("n8n")
        out = await sc_engine.run_extract(_params(text="anything"))
        assert out["_via"] == "proxy" and out["_path"] == "smart-capture/extract"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_shadow_returns_n8n_body_with_native_token(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        monkeypatch.setattr(sc_engine, "_proxy_n8n", _fake_proxy)
        await _set_engine("shadow")
        out = await sc_engine.run_extract(_params(text="chili"))
        # n8n body is authoritative (album intent), but token is re-minted native.
        assert out["_via"] == "proxy" and out["intents"][0]["domain"] == "album"
        assert out["extract_token"] != "n8n-token"
        async with get_pool().acquire() as conn:
            secret = await get_token_secret(conn)
        h = intent_hash("album", {}, None)  # n8n's returned intent, no asset
        ok, reason = sc_tokens.verify(out["extract_token"], h, UID, WID, secret, __import__("time").time())
        assert ok, reason  # the native token verifies over n8n's intents
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_image_extract_proxies_when_flag_off(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        monkeypatch.setattr(sc_engine, "_proxy_n8n", _fake_proxy)
        await _set_engine("native")  # native, but process_asset_native defaults False
        out = await sc_engine.run_extract(_params(image_path="/files/inbox/x.jpg"))
        assert out["_via"] == "proxy"  # M4 fallback
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_commit_dispatch(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        # n8n → proxy
        monkeypatch.setattr(sc_engine, "_proxy_n8n", _fake_proxy)
        await _set_engine("n8n")
        out = await sc_engine.run_commit(_params(domain="tool", payload={"name": "x"}, extract_token="t"))
        assert out["_via"] == "proxy" and out["_path"] == "smart-capture/commit"

        # native → commit_native (real write). Mint a matching token.
        await _set_engine("native")
        payload = {"name": "Native Drill"}
        async with get_pool().acquire() as conn:
            secret = await get_token_secret(conn)
        import time as _t
        tok = sc_tokens.mint([intent_hash("tool", payload, None)], UID, WID, secret, _t.time())
        out2 = await sc_engine.run_commit(_params(domain="tool", payload=payload, extract_token=tok))
        assert out2["ok"] and out2["domain"] == "tool"
        async with get_pool().acquire() as conn:
            n = await conn.fetchval("SELECT count(*) FROM inventory.tools WHERE name='Native Drill'")
        assert n == 1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_executor_injects_context_keys(fresh_db, db_settings):
    """Other native handlers still work with the extra injected keys, and the
    keys are actually present."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        seen = {}

        @native_skill("_test-echo-context")
        async def _echo(params: dict) -> dict:
            seen.update(params)
            return {"ok": True}

        ex = SkillExecutor(Config(
            ANTHROPIC_API_KEY="test", DB_HOST=str(db_settings["host"]),
            DB_PORT=int(db_settings["port"]), DB_NAME=fresh_db,
            DB_USER=str(db_settings["user"]), DB_PASSWORD=str(db_settings["password"]),
            JWT_SECRET="test", N8N_BASE="http://n8n:5678",
        ))
        res = await ex._try_native_skill("_test-echo-context", {"foo": "bar"}, user_id=UID, workspace_id=WID)
        assert res is not None
        assert seen["_user_id"] == UID and seen["_workspace_id"] == WID
        assert seen["foo"] == "bar"
        assert seen["_config"] is not None and seen["_model_provider"] is not None
    finally:
        await close_pool()
