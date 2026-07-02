"""Dashboard V2 Phase 2 — agent event log (bh_agent_events + agent_logger).

DB-backed (throwaway pgvector pg16). Verifies persistence, the jsonb
action_payload round-trip, the newest-first bounded stream push, that the
pushed event is JSON-serializable (the SSE route serializes the whole cache),
level coercion, and hydration.
"""
from __future__ import annotations

import json

import pytest

from backend.database import close_pool
from backend.services import agent_logger
from backend.services.dashboard_stream import DashboardStateCache
from backend.tests.semantic_helpers import apply_migrations


def _reset_cache():
    DashboardStateCache._instance = None


@pytest.mark.asyncio
async def test_log_event_persists_and_streams(fresh_db, db_settings):
    _reset_cache()
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        await agent_logger.log_event(
            "categorizer", "Processed $14.99 as Unknown", level="warning",
            action_payload={"label": "Recategorize", "type": "mutation",
                            "endpoint": "/api/finance/x", "method": "POST", "body": {"id": 1}},
        )

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT source, message, level, action_payload FROM public.bh_agent_events")
        assert row["source"] == "categorizer"
        assert row["level"] == "warning"
        assert row["action_payload"]["label"] == "Recategorize"  # jsonb round-trip → dict

        state = await DashboardStateCache.get_instance().get_all()
        events = state["agent_events"]
        assert len(events) == 1
        assert events[0]["message"] == "Processed $14.99 as Unknown"
        assert isinstance(events[0]["created_at"], str)  # NOT a datetime
        json.dumps(state)  # SSE contract: the whole cache must serialize
    finally:
        _reset_cache()
        await close_pool()


@pytest.mark.asyncio
async def test_invalid_level_coerced_and_hydrate(fresh_db, db_settings):
    _reset_cache()
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        await agent_logger.log_event("sync", "nightly SimpleFin sync ok", level="bogus")
        async with pool.acquire() as conn:
            lvl = await conn.fetchval("SELECT level FROM public.bh_agent_events")
        assert lvl == "info"  # invalid level → info (CHECK would otherwise reject)

        _reset_cache()  # simulate a cold cache; hydrate should refill from the DB
        await agent_logger.hydrate_recent()
        events = (await DashboardStateCache.get_instance().get_all())["agent_events"]
        assert len(events) == 1 and events[0]["source"] == "sync"
    finally:
        _reset_cache()
        await close_pool()


@pytest.mark.asyncio
async def test_append_event_is_bounded_and_newest_first():
    _reset_cache()
    cache = DashboardStateCache.get_instance()
    for i in range(60):
        await cache.append_event({"id": i}, cap=50)
    events = (await cache.get_all())["agent_events"]
    assert len(events) == 50
    assert events[0]["id"] == 59   # newest first
    assert events[-1]["id"] == 10  # oldest dropped past the cap
    _reset_cache()
