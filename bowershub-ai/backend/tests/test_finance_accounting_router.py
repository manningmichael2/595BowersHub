"""Finance-accounting Tasks 7-8 — reconciliation service + typed API router.

Covers R2.1-2.4 (drift, cleared tally, reconcile event + reconciled_through_date),
R3.7 (net-worth endpoint), R1.5 (link/unlink API), R4.1 (set-account-type API),
and RBAC (mutations require admin).
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
from backend.routers.finance_accounting import router as acct_router
from backend.services.accounting.reconciliation import account_status, reconcile
from backend.tests.semantic_helpers import apply_migrations
from backend.services import authz

_ADMIN = {"id": 1, "email": "o@x", "display_name": "Owner", "role": "admin", "is_active": True}
_MEMBER = {"id": 2, "email": "m@x", "display_name": "Member", "role": "member", "is_active": True}
_VIEWER = {"id": 3, "email": "v@x", "display_name": "Viewer", "role": "viewer", "is_active": True}


def _client(user) -> httpx.AsyncClient:
    app = FastAPI()
    app.include_router(acct_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    await authz.init_authz(pool)  # require_capability gates need the warmed cache
    async with pool.acquire() as conn:
        chk = await conn.fetchval(
            "INSERT INTO finance.accounts (id, org_name, account_name, account_type, last_balance, last_balance_date) "
            "VALUES ('ACT-chk', 'Bank', 'Checking', 'checking', 1000, CURRENT_DATE) RETURNING id")
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, cleared) "
            "VALUES ('TRN-1', $1, CURRENT_DATE, -40, 'x', true)", chk)
    try:
        yield {"pool": pool, "chk": chk}
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_reconcile_service(seeded):
    """R2.1/2.3/2.4: drift vs synced, audit row, reconciled_through_date advance."""
    async with seeded["pool"].acquire() as conn:
        st = await account_status(conn, "ACT-chk")
        assert st["synced_balance"] == 1000.0 and st["cleared_tally"] == -40.0
        res = await reconcile(conn, "ACT-chk", date.today(), 990.0)
        assert res["delta"] == -10.0 and res["in_sync"] is False
        assert await conn.fetchval(
            "SELECT count(*) FROM finance.reconciliations WHERE account_id='ACT-chk'") == 1
        assert await conn.fetchval(
            "SELECT reconciled_through_date FROM finance.accounts WHERE id='ACT-chk'") == date.today()


@pytest.mark.asyncio
async def test_net_worth_endpoint(seeded):
    async with _client(_MEMBER) as c:
        r = await c.get("/api/finance/net-worth")
    assert r.status_code == 200
    assert r.json()["net_worth"] == 1000.0


@pytest.mark.asyncio
async def test_set_account_type_rbac(seeded):
    # member denied
    async with _client(_MEMBER) as c:
        r = await c.put("/api/finance/accounts/ACT-chk/type", json={"account_type": "savings"})
    assert r.status_code == 403
    # admin ok
    async with _client(_ADMIN) as c:
        r = await c.put("/api/finance/accounts/ACT-chk/type", json={"account_type": "savings"})
    assert r.status_code == 200
    async with seeded["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT account_type FROM finance.accounts WHERE id='ACT-chk'") == "savings"


@pytest.mark.asyncio
async def test_reconcile_endpoint_is_finance_write(seeded):
    # reconcile is finance.write=member (0039): a viewer is denied, a member allowed.
    async with _client(_VIEWER) as c:
        r = await c.post("/api/finance/accounts/ACT-chk/reconcile",
                         json={"statement_date": str(date.today()), "statement_balance": 1000.0})
    assert r.status_code == 403
    async with _client(_MEMBER) as c:
        r = await c.post("/api/finance/accounts/ACT-chk/reconcile",
                         json={"statement_date": str(date.today()), "statement_balance": 1000.0})
    assert r.status_code == 200 and r.json()["in_sync"] is True


@pytest.mark.asyncio
async def test_link_unlink_api(seeded):
    async with seeded["pool"].acquire() as conn:
        sav = await conn.fetchval(
            "INSERT INTO finance.accounts (id, org_name, account_name, account_type, last_balance) "
            "VALUES ('ACT-sav', 'Bank', 'Savings', 'savings', 500) RETURNING id")
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
            "VALUES ('TRN-a', 'ACT-chk', CURRENT_DATE, -200, 'xfer'), "
            "       ('TRN-b', 'ACT-sav', CURRENT_DATE, 200, 'xfer')")
    async with _client(_ADMIN) as c:
        r = await c.post("/api/finance/transactions/link", json={"a_id": "TRN-a", "b_id": "TRN-b"})
        assert r.status_code == 200
        r2 = await c.post("/api/finance/transactions/unlink", json={"id": "TRN-a"})
        assert r2.status_code == 200
    async with seeded["pool"].acquire() as conn:
        assert await conn.fetchval("SELECT transfer_id FROM finance.transactions WHERE id='TRN-a'") is None
