"""Task 3 — native extract: intent shape, fence-strip, other-fallback, allow-list,
oversized rejection, model-error handling, and token membership. (n8n-decommission)
"""

from __future__ import annotations

import json
import time

import pytest

from backend.database import close_pool
from backend.models.message import CompletionResult
from backend.services.smart_capture import tokens as sc_tokens
from backend.services.smart_capture.config import get_token_secret
from backend.services.smart_capture.extract import MAX_INPUT_CHARS, extract_native
from backend.services.smart_capture.intents import intent_hash
from backend.tests.semantic_helpers import apply_migrations

NOW = 1_000_000.0


class FakeProvider:
    def __init__(self, content: str | None = None, raise_exc: Exception | None = None):
        self._content = content
        self._raise = raise_exc
        self.calls: list[dict] = []

    async def complete(self, **kwargs):
        self.calls.append(kwargs)
        if self._raise:
            raise self._raise
        return CompletionResult(content=self._content, model="fake", input_tokens=1, output_tokens=1)


async def _extract(conn, provider, text="hello", domain_hint=None, asset=None):
    return await extract_native(
        text=text,
        domain_hint=domain_hint,
        user_id=7,
        workspace_id=3,
        model_provider=provider,
        conn=conn,
        now=NOW,
        asset=asset,
    )


@pytest.mark.asyncio
async def test_text_capture_expected_shape_and_token(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            content = json.dumps(
                {"intents": [{"domain": "shopping_list", "summary": "add milk",
                              "payload": {"items": ["milk"]}, "needs_more_info": []}]}
            )
            out = await _extract(conn, FakeProvider(content), text="buy milk")
            assert out["ok"] is True
            assert out["raw_text"] == "buy milk"
            assert out["asset"] is None
            assert len(out["intents"]) == 1
            it = out["intents"][0]
            assert it["domain"] == "shopping_list" and it["payload"] == {"items": ["milk"]}
            assert set(it) == {"domain", "summary", "payload", "needs_more_info"}

            # Token verifies for the returned intent (membership).
            secret = await get_token_secret(conn)
            h = intent_hash("shopping_list", {"items": ["milk"]}, None)
            ok, reason = sc_tokens.verify(out["extract_token"], h, 7, 3, secret, NOW)
            assert ok, reason
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_fenced_json_is_stripped(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            content = "```json\n" + json.dumps(
                {"intents": [{"domain": "tool", "summary": "s", "payload": {"name": "drill"}}]}
            ) + "\n```"
            out = await _extract(conn, FakeProvider(content))
            assert out["ok"] and out["intents"][0]["domain"] == "tool"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_unparseable_output_falls_back_to_other(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            out = await _extract(conn, FakeProvider("not json at all {broken"), text="mystery note")
            assert out["ok"] is True  # never partial — always yields something
            assert len(out["intents"]) == 1
            it = out["intents"][0]
            assert it["domain"] == "other"
            assert it["payload"]["content"].startswith("mystery note")
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_domain_allow_list_enforced(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            content = json.dumps(
                {"intents": [{"domain": "cryptocurrency", "summary": "buy btc",
                              "payload": {"coin": "BTC"}}]}
            )
            out = await _extract(conn, FakeProvider(content))
            assert out["intents"][0]["domain"] == "other"  # coerced, not passed through
            # original payload preserved inside content
            assert "BTC" in out["intents"][0]["payload"]["content"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_oversized_input_rejected(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            prov = FakeProvider(json.dumps({"intents": []}))
            out = await _extract(conn, prov, text="x" * (MAX_INPUT_CHARS + 1))
            assert out["ok"] is False and "too large" in out["error"]
            assert prov.calls == []  # rejected before the model call
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_empty_input_rejected(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            out = await _extract(conn, FakeProvider("{}"), text="   ", asset=None)
            assert out["ok"] is False and "provide" in out["error"].lower()
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_model_error_returns_clear_error(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            out = await _extract(conn, FakeProvider(raise_exc=RuntimeError("503 overloaded")))
            assert out["ok"] is False
            assert "failed" in out["error"].lower() and "503" in out["error"]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_multi_intent_each_verifies(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            content = json.dumps({"intents": [
                {"domain": "recipe", "summary": "r", "payload": {"title": "Chili"}},
                {"domain": "shopping_list", "summary": "s", "payload": {"items": ["beans"]}},
            ]})
            out = await _extract(conn, FakeProvider(content), text="chili recipe + beans")
            assert len(out["intents"]) == 2
            secret = await get_token_secret(conn)
            for it in out["intents"]:
                h = intent_hash(it["domain"], it["payload"], None)
                assert sc_tokens.verify(out["extract_token"], h, 7, 3, secret, NOW)[0]
    finally:
        await close_pool()
