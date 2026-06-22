"""ai-finance-insights Task 8 — insight store lifecycle (R2.4, R2.7)."""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services.finance_insights.config import load_insight_config
from backend.services.finance_insights.detectors import Candidate
from backend.services.finance_insights import store
from backend.tests.semantic_helpers import apply_migrations


def _cand(merchant="acme", period="2026-06", impact=10.0, itype="duplicate_charge"):
    return Candidate(itype, merchant, period, impact, {"amount": impact}, "because")


@pytest.mark.asyncio
async def test_rerun_is_idempotent_and_ranks_by_impact(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cfg = await load_insight_config(conn)
            cands = [_cand("small", impact=5.0), _cand("big", impact=99.0)]
            new1 = await store.upsert_candidates(conn, cands, cfg)
            assert len(new1) == 2                    # both newly raised
            new2 = await store.upsert_candidates(conn, cands, cfg)
            assert new2 == []                        # full re-run → no duplicates

            listed = await store.list_insights(conn, status="active")
            assert len(listed) == 2
            assert [r["merchant_key"] for r in listed] == ["big", "small"]  # impact desc
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_dismiss_blocks_reraise_then_reopen_restores(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cfg = await load_insight_config(conn)
            [iid] = await store.upsert_candidates(conn, [_cand()], cfg)

            assert await store.dismiss(conn, iid) is True
            # Re-run must NOT resurrect the dismissed insight.
            assert await store.upsert_candidates(conn, [_cand()], cfg) == []
            assert await store.list_insights(conn, status="active") == []
            row = (await store.list_insights(conn, status="dismissed"))[0]
            assert row["id"] == iid

            # Reopen makes it visible again.
            assert await store.reopen(conn, iid) is True
            active = await store.list_insights(conn, status="active")
            assert [r["id"] for r in active] == [iid]
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_new_month_reraises_as_new_period(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            cfg = await load_insight_config(conn)
            [iid] = await store.upsert_candidates(conn, [_cand(period="2026-06")], cfg)
            await store.dismiss(conn, iid)
            # Same (type, merchant) but a NEW period is a legitimate new insight.
            new = await store.upsert_candidates(conn, [_cand(period="2026-07")], cfg)
            assert len(new) == 1
            assert len(await store.list_insights(conn, status="active")) == 1
    finally:
        await close_pool()
