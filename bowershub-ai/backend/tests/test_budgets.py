"""Finance-budgets-splits Tasks 4-6 — budgets service + API.

Covers R3.1/R3.2/R3.3 (reuse finance.budgets, CRUD, allocation-aware actual) and
R3.5 (config-driven thresholds), plus RBAC on the write.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from datetime import date
from fastapi import FastAPI
from httpx import ASGITransport

from backend.database import close_pool
from backend.middleware.auth import get_current_user
from backend.routers.finance_budgets import router as budgets_router
from backend.services.budgets import alert_thresholds, budget_vs_actual, upsert_budget
from backend.services.splits import create_split
from backend.tests.semantic_helpers import apply_migrations

_ADMIN = {"id": 1, "email": "o@x", "display_name": "O", "role": "admin", "is_active": True}
_MEMBER = {"id": 2, "email": "m@x", "display_name": "M", "role": "member", "is_active": True}
_MONTH = date.today().replace(day=1)


def _client(user) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(budgets_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    async with pool.acquire() as conn:
        acct = await conn.fetchval(
            "INSERT INTO finance.accounts (id, org_name, account_name, account_type) "
            "VALUES ('A1', 'Bank', 'Checking', 'checking') RETURNING id")
        cats = [r["id"] for r in await conn.fetch("SELECT id FROM finance.categories ORDER BY id LIMIT 2")]
        # one normal spend in cat0 this month
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, category_id) "
            "VALUES ('T1', $1, CURRENT_DATE, -30, 'x', $2)", acct, cats[0])
    try:
        yield {"pool": pool, "acct": acct, "cats": cats}
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_thresholds_from_config(seeded):
    async with seeded["pool"].acquire() as conn:
        warn, over = await alert_thresholds(conn)
    assert warn == 0.8 and over == 1.0  # seeded by 0032


@pytest.mark.asyncio
async def test_budget_vs_actual_allocation_aware(seeded):
    c0, c1 = seeded["cats"]
    async with seeded["pool"].acquire() as conn:
        await upsert_budget(conn, c0, _MONTH, 100.0)
        # split a new txn across c0 + c1 → each child counts to its own category
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
            "VALUES ('T2', $1, CURRENT_DATE, -50, 'split')", seeded["acct"])
        await create_split(conn, "T2", [{"category_id": c0, "amount": -20}, {"category_id": c1, "amount": -30}])
        rows = {r["category_id"]: r for r in await budget_vs_actual(conn, _MONTH)}
    # c0 actual = 30 (normal) + 20 (split child) = 50; budget 100 → remaining 50
    assert rows[c0]["budgeted"] == 100.0 and rows[c0]["actual"] == 50.0 and rows[c0]["remaining"] == 50.0
    # c1 has spend (30 from split child) but no budget
    assert rows[c1]["actual"] == 30.0


@pytest.mark.asyncio
async def test_budget_api_rbac_and_roundtrip(seeded):
    c0 = seeded["cats"][0]
    async with _client(_MEMBER) as c:
        r = await c.put("/api/finance/budgets", json={"category_id": c0, "month": _MONTH.isoformat(), "limit_amount": 200})
    assert r.status_code == 403
    async with _client(_ADMIN) as c:
        r = await c.put("/api/finance/budgets", json={"category_id": c0, "month": _MONTH.isoformat(), "limit_amount": 200})
        assert r.status_code == 200
        g = await c.get(f"/api/finance/budgets?month={_MONTH.isoformat()}")
        assert g.status_code == 200 and g.json()["budgets"][0]["limit_amount"] == 200.0
        a = await c.get(f"/api/finance/budgets/actual?month={_MONTH.isoformat()}")
        assert a.status_code == 200
