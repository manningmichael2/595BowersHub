"""Per-account owner (household): tag whose account it is, list owners, and
filter transactions by owner. Display/filter only — not an access boundary.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import authz
from backend.services.auth import AuthService


pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-account-owner",
        N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    auth = AuthService(pool, config)
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('a@t','x','A','admin') RETURNING id")
        manon_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t','x','Manon','member') RETURNING id")
        # Two accounts: one will be Manon's, one stays Joint (NULL owner).
        for acct in ("acct_manon", "acct_joint"):
            await conn.execute(
                "INSERT INTO finance.accounts (id, org_name, account_name) VALUES ($1,$2,$3)",
                acct, "Bank", acct)
        # One transaction in each account.
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
            "VALUES ('t_m','acct_manon','2026-06-01',-10,'manon coffee')")
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description) "
            "VALUES ('t_j','acct_joint','2026-06-01',-20,'joint groceries')")
    headers = {
        "admin": {"Authorization": "Bearer " + auth.generate_access_token(admin_id, "a@t", "admin")},
        "member": {"Authorization": "Bearer " + auth.generate_access_token(manon_id, "m@t", "member")},
    }
    app = FastAPI()
    app.state.config = config
    from backend.routers.finance_accounting import router as acc
    from backend.routers.finance_transactions import router as txns
    app.include_router(acc)
    app.include_router(txns)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "manon_id": manon_id, "headers": headers}
        finally:
            await close_pool()


async def test_assign_owner_then_filter(env):
    c, headers, manon = env["client"], env["headers"], env["manon_id"]

    # Assign acct_manon to Manon (admin / finance.delete).
    r = await c.put("/api/finance/accounts/acct_manon/owner",
                    json={"owner_id": manon}, headers=headers["admin"])
    assert r.status_code == 200 and r.json()["owner_id"] == manon

    # The owner shows up in the accounts listing.
    r = await c.get("/api/finance/accounts", headers=headers["admin"])
    by_id = {a["id"]: a for a in r.json()}
    assert by_id["acct_manon"]["owner_name"] == "Manon"
    assert by_id["acct_joint"]["owner_id"] is None

    # Filter transactions by Manon → only her account's txn.
    r = await c.get(f"/api/finance/transactions?owner={manon}", headers=headers["admin"])
    items = r.json()["items"]
    assert {i["id"] for i in items} == {"t_m"}

    # Filter by Joint (unowned) → only the joint account's txn.
    r = await c.get("/api/finance/transactions?owner=joint", headers=headers["admin"])
    assert {i["id"] for i in r.json()["items"]} == {"t_j"}

    # No owner filter → both.
    r = await c.get("/api/finance/transactions", headers=headers["admin"])
    assert {i["id"] for i in r.json()["items"]} == {"t_m", "t_j"}


async def test_set_owner_to_joint(env):
    c, headers, manon = env["client"], env["headers"], env["manon_id"]
    await c.put("/api/finance/accounts/acct_manon/owner",
                json={"owner_id": manon}, headers=headers["admin"])
    # owner_id=null clears it back to Joint.
    r = await c.put("/api/finance/accounts/acct_manon/owner",
                    json={"owner_id": None}, headers=headers["admin"])
    assert r.status_code == 200 and r.json()["owner_id"] is None


async def test_bad_owner_and_missing_account(env):
    c, headers = env["client"], env["headers"]
    assert (await c.put("/api/finance/accounts/acct_manon/owner",
                        json={"owner_id": 99999}, headers=headers["admin"])).status_code == 400
    assert (await c.put("/api/finance/accounts/nope/owner",
                        json={"owner_id": None}, headers=headers["admin"])).status_code == 404


async def test_member_can_read_but_not_assign(env):
    c, headers, manon = env["client"], env["headers"], env["manon_id"]
    # Member can list accounts + filter (finance.read) ...
    assert (await c.get("/api/finance/accounts", headers=headers["member"])).status_code == 200
    assert (await c.get(f"/api/finance/transactions?owner={manon}",
                        headers=headers["member"])).status_code == 200
    # ... but cannot assign owners (finance.delete = admin-only).
    assert (await c.put("/api/finance/accounts/acct_manon/owner",
                        json={"owner_id": manon}, headers=headers["member"])).status_code == 403
