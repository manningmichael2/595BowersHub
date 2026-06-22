"""ai-finance-insights Task 10 — insights API + morning-card gatherer (R2.5, R2.6)."""

from __future__ import annotations

import pytest

from backend.database import close_pool, get_pool
from backend.routers.finance_insights import (
    list_insights, dismiss_insight, reopen_insight, action_insight,
)
from backend.services.briefing import BriefingService
from backend.services.briefing_summary import parse_sections
from backend.services.finance_insights.config import load_insight_config
from backend.services.finance_insights.detectors import Candidate
from backend.services.finance_insights import store
from backend.tests.semantic_helpers import apply_migrations


async def _seed_insight(impact=42.0, merchant="acme"):
    async with get_pool().acquire() as conn:
        cfg = await load_insight_config(conn)
        ids = await store.upsert_candidates(
            conn,
            [Candidate("duplicate_charge", merchant, "2026-06", impact,
                       {"amount": impact}, f"Two charges at {merchant}")],
            cfg,
        )
    return ids[0]


@pytest.mark.asyncio
async def test_list_dismiss_reopen_via_api(fresh_db, db_settings):
    await apply_migrations(fresh_db, db_settings)
    try:
        iid = await _seed_insight()
        listed = await list_insights(status="active", user={"id": 1})
        assert [i["id"] for i in listed["insights"]] == [iid]
        assert listed["insights"][0]["reason"]

        await dismiss_insight(iid, user={"id": 1})
        assert await list_insights(status="active", user={"id": 1}) == {"insights": []}
        assert len((await list_insights(status="dismissed", user={"id": 1}))["insights"]) == 1

        await reopen_insight(iid, user={"id": 1})
        assert len((await list_insights(status="active", user={"id": 1}))["insights"]) == 1

        await action_insight(iid, user={"id": 1})
        assert len((await list_insights(status="actioned", user={"id": 1}))["insights"]) == 1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_morning_card_section_has_content_when_insights_exist(fresh_db, db_settings):
    """M1: with active insights, the finance_insights section renders content, not
    the `—` placeholder."""
    await apply_migrations(fresh_db, db_settings)
    try:
        # No insights yet → gatherer returns None → section omitted → placeholder.
        svc = BriefingService(model_provider=None, skill_executor=None, config=None)
        assert await svc._get_insights() is None

        await _seed_insight(impact=15.0, merchant="netflix")
        gathered = await svc._get_insights()
        assert gathered is not None and "netflix" in gathered

        # Parsed into the morning card, the section carries content.
        markdown = f"**Finance Insights:**\n\n{gathered}\n"
        section = {s["key"]: s for s in parse_sections(markdown)}["finance_insights"]
        assert section["content"] != "—"
        assert "netflix" in section["content"]
    finally:
        await close_pool()
