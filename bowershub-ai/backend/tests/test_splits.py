"""Finance-budgets-splits Tasks 2-3-5 — splits service, allocation-aware rollups, API.

Covers R1.2-1.6 (split integrity, parent container, unsplit, transfer boundary),
R2.1/R2.4 (children count per category via real_activity, parent excluded, sums
unchanged), R1.4 (API + RBAC).
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from backend.database import close_pool
from backend.middleware.auth import get_current_user
from backend.routers.finance_review import router as review_router
from backend.services.splits import create_split, get_allocations, unsplit
from backend.tests.semantic_helpers import apply_migrations

_ADMIN = {"id": 1, "email": "o@x", "display_name": "O", "role": "admin", "is_active": True}
_MEMBER = {"id": 2, "email": "m@x", "display_name": "M", "role": "member", "is_active": True}


def _client(user) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(review_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    async with pool.acquire() as conn:
        acct = await conn.fetchval(
            "INSERT INTO finance.accounts (id, org_name, account_name, account_type) "
            "VALUES ('A1', 'Bank', 'Checking', 'checking') RETURNING id")
        cats = [r["id"] for r in await conn.fetch("SELECT id FROM finance.categories LIMIT 2")]
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
            "VALUES ('T100', $1, CURRENT_DATE, -100, 'Target')", acct)
    try:
        yield {"pool": pool, "acct": acct, "cats": cats}
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_create_split_and_rollup(seeded):
    c0, c1 = seeded["cats"]
    async with seeded["pool"].acquire() as conn:
        before = await conn.fetchval("SELECT COALESCE(SUM(amount),0) FROM public.real_activity")
        await create_split(conn, "T100", [{"category_id": c0, "amount": -60}, {"category_id": c1, "amount": -40}])
        parent = await conn.fetchrow("SELECT is_split, category_id, user_category_override FROM finance.transactions WHERE id='T100'")
        assert parent["is_split"] is True and parent["category_id"] is None and parent["user_category_override"] is True
        kids = await get_allocations(conn, "T100")
        assert len(kids) == 2 and sorted(k["amount"] for k in kids) == [-60.0, -40.0]
        # Children inherit account + date
        child_acct = await conn.fetchval("SELECT account_id FROM finance.transactions WHERE parent_id='T100' LIMIT 1")
        assert child_acct == seeded["acct"]
        # Rollup invariant: real_activity total unchanged (parent out, children in)
        after = await conn.fetchval("SELECT COALESCE(SUM(amount),0) FROM public.real_activity")
        assert float(after) == float(before)
        # Per-category: each child counts to its own category, parent absent
        per_cat = {r["category_id"]: float(r["s"]) for r in await conn.fetch(
            "SELECT category_id, SUM(amount) s FROM public.real_activity WHERE category_id = ANY($1::int[]) GROUP BY category_id", [c0, c1])}
        assert per_cat[c0] == -60.0 and per_cat[c1] == -40.0


@pytest.mark.asyncio
async def test_split_rejects_bad_sum_and_transfer(seeded):
    c0, c1 = seeded["cats"]
    async with seeded["pool"].acquire() as conn:
        with pytest.raises(ValueError):
            await create_split(conn, "T100", [{"category_id": c0, "amount": -60}, {"category_id": c1, "amount": -50}])
        await conn.execute("UPDATE finance.transactions SET is_transfer=true WHERE id='T100'")
        with pytest.raises(ValueError):
            await create_split(conn, "T100", [{"category_id": c0, "amount": -60}, {"category_id": c1, "amount": -40}])


@pytest.mark.asyncio
async def test_unsplit_restores(seeded):
    c0, c1 = seeded["cats"]
    async with seeded["pool"].acquire() as conn:
        await create_split(conn, "T100", [{"category_id": c0, "amount": -60}, {"category_id": c1, "amount": -40}])
        await unsplit(conn, "T100")
        row = await conn.fetchrow("SELECT is_split, user_category_override FROM finance.transactions WHERE id='T100'")
        assert row["is_split"] is False and row["user_category_override"] is False
        assert await conn.fetchval("SELECT count(*) FROM finance.transactions WHERE parent_id='T100'") == 0


@pytest.mark.asyncio
async def test_split_api_rbac_and_validation(seeded):
    c0, c1 = seeded["cats"]
    async with _client(_MEMBER) as c:
        r = await c.post("/api/finance/transactions/T100/split",
                         json={"allocations": [{"category_id": c0, "amount": -60}, {"category_id": c1, "amount": -40}]})
    assert r.status_code == 403
    async with _client(_ADMIN) as c:
        r = await c.post("/api/finance/transactions/T100/split",
                         json={"allocations": [{"category_id": c0, "amount": -60}, {"category_id": c1, "amount": -40}]})
        assert r.status_code == 200 and r.json()["children"] == 2
        bad = await c.post("/api/finance/transactions/T100/split",
                           json={"allocations": [{"category_id": c0, "amount": -60}, {"category_id": c1, "amount": -50}]})
        assert bad.status_code == 400
