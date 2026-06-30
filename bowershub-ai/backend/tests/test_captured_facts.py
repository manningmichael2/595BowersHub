"""Captured-facts admin endpoints + weekly digest (proactive-assistant monitoring)."""
from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.routers import admin
from backend.services import alerts

pytestmark = pytest.mark.asyncio


def _config(db_name: str, s: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="t", DB_HOST=str(s["host"]), DB_PORT=int(s["port"]),
        DB_NAME=db_name, DB_USER=str(s["user"]), DB_PASSWORD=str(s["password"]),
        JWT_SECRET="test-secret-captured", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    pool = await init_pool(_config(fresh_db, db_settings))
    await run_migrations(pool)
    async with pool.acquire() as conn:
        uid = await conn.fetchval(
            "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
            "VALUES ('mi@t','x','Michael','admin') RETURNING id")
    try:
        yield {"pool": pool, "uid": uid}
    finally:
        await close_pool()


async def _add_entity(conn, name, summary, source, created_by=None, days_ago=0,
                      captured_by="Michael"):
    return await conn.fetchval(
        """
        INSERT INTO public.bh_entities
            (name, entity_type, summary, attributes, source, created_by, created_at)
        VALUES ($1,'preference',$2,$3::jsonb,$4,$5, now() - make_interval(days => $6))
        RETURNING id
        """,
        name, summary,
        '{"captured_by":"%s","auto_captured":true}' % captured_by,
        source, created_by, days_ago)


# ── admin endpoints ───────────────────────────────────────────────────────────

async def test_list_only_returns_auto_captured(env):
    async with env["pool"].acquire() as conn:
        await _add_entity(conn, "fact a", "Michael is allergic to walnuts",
                          "context_capture", env["uid"])
        await _add_entity(conn, "manual", "taught via /remember", "chat", env["uid"])
    out = await admin.list_captured_facts(user={"id": env["uid"]}, limit=50, offset=0)
    assert out["total"] == 1
    assert out["facts"][0]["summary"] == "Michael is allergic to walnuts"
    assert out["facts"][0]["captured_by"] == "Michael"


async def test_delete_is_scoped_and_soft(env):
    async with env["pool"].acquire() as conn:
        cap_id = await _add_entity(conn, "f", "auto fact", "context_capture", env["uid"])
        chat_id = await _add_entity(conn, "m", "manual fact", "chat", env["uid"])

    # Cannot delete a manually-taught entity through this endpoint.
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as ei:
        await admin.delete_captured_fact(chat_id, user={"id": env["uid"]})
    assert ei.value.status_code == 404

    # Deleting an auto-captured fact deactivates it (soft) and drops it from the list.
    res = await admin.delete_captured_fact(cap_id, user={"id": env["uid"]})
    assert res["deleted"] == cap_id
    async with env["pool"].acquire() as conn:
        active = await conn.fetchval(
            "SELECT is_active FROM public.bh_entities WHERE id=$1", cap_id)
    assert active is False
    out = await admin.list_captured_facts(user={"id": env["uid"]}, limit=50, offset=0)
    assert out["total"] == 0

    # Double-delete → 404 (already inactive).
    with pytest.raises(HTTPException):
        await admin.delete_captured_fact(cap_id, user={"id": env["uid"]})


# ── weekly digest ─────────────────────────────────────────────────────────────

class _StubNotifier:
    def __init__(self):
        self.calls = []

    async def notify_users(self, recipients, **kw):
        self.calls.append({"recipients": recipients, **kw})
        return {"delivered": len(recipients)}


@pytest_asyncio.fixture
async def stub_notifier(monkeypatch):
    stub = _StubNotifier()
    monkeypatch.setattr(alerts, "_get_notifier", lambda: stub)
    return stub


async def test_digest_sends_recent_facts(env, stub_notifier):
    async with env["pool"].acquire() as conn:
        await _add_entity(conn, "a", "Michael is allergic to walnuts", "context_capture",
                          env["uid"], days_ago=1)
        await _add_entity(conn, "b", "Manon is vegetarian", "context_capture",
                          env["uid"], days_ago=2, captured_by="Manon")
        await _add_entity(conn, "old", "stale fact", "context_capture",
                          env["uid"], days_ago=30)        # outside the 7-day window
        await _add_entity(conn, "manual", "taught", "chat", env["uid"], days_ago=1)
    await alerts.check_capture_digest()
    assert len(stub_notifier.calls) == 1
    call = stub_notifier.calls[0]
    assert "2 things" in call["title"]
    assert "walnuts" in call["message"] and "vegetarian" in call["message"]
    assert env["uid"] in call["recipients"]


async def test_digest_silent_when_nothing_recent(env, stub_notifier):
    async with env["pool"].acquire() as conn:
        await _add_entity(conn, "old", "stale", "context_capture", env["uid"], days_ago=30)
    await alerts.check_capture_digest()
    assert stub_notifier.calls == []


async def test_digest_respects_disabled_setting(env, stub_notifier):
    async with env["pool"].acquire() as conn:
        await _add_entity(conn, "a", "recent fact", "context_capture", env["uid"], days_ago=1)
        await conn.execute(
            "INSERT INTO public.bh_platform_settings (key, value_json) "
            "VALUES ('context_capture.digest_enabled', '{\"enabled\":false}'::jsonb)")
    await alerts.check_capture_digest()
    assert stub_notifier.calls == []
