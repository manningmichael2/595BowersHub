"""Dashboard V2 Task 8 — Generative UI: spec validation + per-user persistence.

`validate_spec` is pure; upsert/list/remove are DB-backed (throwaway pgvector).
"""
from __future__ import annotations

import pytest

from backend.database import close_pool, get_pool
from backend.services import generated_widgets as gw
from backend.services.dashboard_stream import DashboardStateCache
from backend.tests.semantic_helpers import apply_migrations


async def _make_user(email: str) -> int:
    """bh_dashboard_layouts.user_id FKs bh_users, so seed a real user."""
    async with get_pool().acquire() as conn:
        return await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ($1,'x','U','admin') RETURNING id",
            email,
        )


# ---- validate_spec (pure) ---------------------------------------------------

def test_validate_metric_ok():
    out = gw.validate_spec({"type": "metric", "title": "Spend", "value": 1240, "delta": "+3%", "delta_positive": False})
    assert out == {"type": "metric", "title": "Spend", "value": "1240", "delta": "+3%", "delta_positive": False}


def test_validate_list_and_bar_ok():
    assert gw.validate_spec({"type": "list", "title": "Todo", "items": ["a", "b"]})["items"] == ["a", "b"]
    bar = gw.validate_spec({"type": "bar", "title": "By cat", "rows": [{"label": "Food", "value": 5}]})
    assert bar["rows"] == [{"label": "Food", "value": 5.0}]


@pytest.mark.parametrize("spec", [
    {"type": "pie", "title": "x"},                      # unknown type
    {"type": "metric", "title": ""},                    # empty title
    {"type": "metric", "title": "x"},                   # missing value
    {"type": "list", "title": "x", "items": []},        # empty list
    {"type": "bar", "title": "x", "rows": [{"label": "a"}]},  # row missing value
    "not-an-object",
])
def test_validate_rejects_bad_specs(spec):
    with pytest.raises(ValueError):
        gw.validate_spec(spec)


def test_validate_truncates_and_drops_junk():
    out = gw.validate_spec({"type": "list", "title": "T" * 200, "items": ["ok", {"bad": 1}, 42]})
    assert len(out["title"]) == 80
    assert out["items"] == ["ok", "42"]  # dict dropped, number coerced


# ---- persistence (DB-backed) ------------------------------------------------

@pytest.mark.asyncio
async def test_upsert_list_remove_and_epoch(fresh_db, db_settings):
    DashboardStateCache._instance = None
    await apply_migrations(fresh_db, db_settings)
    try:
        u1 = await _make_user("u1@example.com")
        u2 = await _make_user("u2@example.com")
        wid = await gw.upsert_generated(u1, {"type": "metric", "title": "Net worth", "value": "$500k"})
        got = await gw.list_generated(u1)
        assert len(got) == 1 and got[0]["id"] == wid and got[0]["spec"]["title"] == "Net worth"

        # epoch bumped on the shared cache
        assert (await DashboardStateCache.get_instance().get_all())["layout_epoch"] >= 1

        # scoped per user — the other user sees nothing
        assert await gw.list_generated(u2) == []

        await gw.remove_generated(u1, wid)
        assert await gw.list_generated(u1) == []
    finally:
        DashboardStateCache._instance = None
        await close_pool()


@pytest.mark.asyncio
async def test_cap_keeps_newest(fresh_db, db_settings):
    DashboardStateCache._instance = None
    await apply_migrations(fresh_db, db_settings)
    try:
        uid = await _make_user("cap@example.com")
        for i in range(gw.MAX_GENERATED + 2):
            await gw.upsert_generated(uid, {"type": "metric", "title": f"m{i}", "value": str(i)})
        got = await gw.list_generated(uid)
        assert len(got) == gw.MAX_GENERATED
        titles = [w["spec"]["title"] for w in got]
        assert titles[0] == f"m{gw.MAX_GENERATED + 1}"  # newest first, oldest dropped
    finally:
        DashboardStateCache._instance = None
        await close_pool()
