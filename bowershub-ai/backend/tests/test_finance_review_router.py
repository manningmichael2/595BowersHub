"""Task 11 — typed Finance Review write API (R4).

Endpoint contracts; RBAC denies non-owner on writes; single + bulk corrections
fire learning; apply-to-merchant mass-recategorizes with provenance; recurring
grouping; DB-down → typed 503.
"""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from backend.database import close_pool
from backend.middleware.auth import get_current_user, require_admin
from backend.routers.finance_review import router as finance_router
from backend.tests.semantic_helpers import apply_migrations
from backend.services import authz

_ADMIN = {"id": 1, "email": "owner@x", "display_name": "Owner", "role": "admin", "is_active": True}
_MEMBER = {"id": 2, "email": "m@x", "display_name": "Member", "role": "member", "is_active": True}
_VIEWER = {"id": 3, "email": "v@x", "display_name": "Viewer", "role": "viewer", "is_active": True}


def _client(user) -> httpx.AsyncClient:
    """Async client bound to the running test event loop (so it shares the
    asyncpg pool's loop — the sync TestClient spawns its own loop and breaks)."""
    app = FastAPI()
    app.include_router(finance_router)
    # require_admin depends on get_current_user; overriding it makes the real
    # role check see our fake user.
    app.dependency_overrides[get_current_user] = lambda: user
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest_asyncio.fixture
async def seeded(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    await authz.init_authz(pool)  # require_capability gates need the warmed cache
    async with pool.acquire() as conn:
        # Seed the fake _ADMIN/_MEMBER as real bh_users rows so attribution
        # stamping (updated_by FK -> bh_users) is satisfiable. In production
        # get_current_user always yields a live row; the override fakes that.
        for uid, email, name, role in [
            (1, "owner@x", "Owner", "admin"), (2, "m@x", "Member", "member")]:
            await conn.execute(
                "INSERT INTO public.bh_users (id, email, password_hash, display_name, role) "
                "VALUES ($1,$2,'x',$3,$4) ON CONFLICT (id) DO NOTHING", uid, email, name, role)
        acct = await conn.fetchval(
            "INSERT INTO finance.accounts (id, org_name, account_name) "
            "VALUES (gen_random_uuid()::text, 'T', 'CC') RETURNING id")
        dining = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Dining'")
        groceries = await conn.fetchval("SELECT id FROM finance.categories WHERE name='Food_Groceries'")
        ids = {}
        for label, desc, key in [("a", "SQ *SUNRISE BAKERY", "SUNRISE BAKERY"),
                                 ("b", "SUNRISE BAKERY CAFE", "SUNRISE BAKERY"),
                                 ("c", "KROGER #1", "KROGER")]:
            ids[label] = await conn.fetchval(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, "
                "merchant_key) VALUES (gen_random_uuid()::text, $1, CURRENT_DATE, -10.00, $2, $3) RETURNING id",
                acct, desc, key)
    try:
        yield {"pool": pool, "acct": acct, "dining": dining, "groceries": groceries, "ids": ids}
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_review_queue_returns_uncategorized(seeded):
    async with _client(_ADMIN) as client:
        r = await client.get("/api/finance/review-queue")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3  # all uncategorized
    assert {i["merchant_key"] for i in body["items"]} == {"SUNRISE BAKERY", "KROGER"}


@pytest.mark.asyncio
async def test_categories_list(seeded):
    async with _client(_ADMIN) as client:
        r = await client.get("/api/finance/categories")
    assert r.status_code == 200
    names = {c["name"] for c in r.json()}
    assert "Food_Dining" in names and "Food_Groceries" in names


@pytest.mark.asyncio
async def test_categorize_sets_override_and_learns(seeded):
    tid = seeded["ids"]["a"]
    async with _client(_ADMIN) as client:
        r = await client.post(f"/api/finance/transactions/{tid}/categorize",
                              json={"category_id": seeded["dining"]})
    assert r.status_code == 200 and r.json()["updated"] == 1
    async with seeded["pool"].acquire() as conn:
        row = await conn.fetchrow(
            "SELECT category_id, user_category_override FROM finance.transactions WHERE id=$1", tid)
        learned = await conn.fetchval(
            "SELECT count(*) FROM finance.merchant_memory WHERE merchant_key='SUNRISE BAKERY'")
    assert row["category_id"] == seeded["dining"] and row["user_category_override"] is True
    assert learned == 1  # learning fired


@pytest.mark.asyncio
async def test_rbac_member_writes_viewer_read_only(seeded):
    tid = seeded["ids"]["a"]
    # finance.write=member (0039): a member can categorize.
    async with _client(_MEMBER) as client:
        r = await client.post(f"/api/finance/transactions/{tid}/categorize",
                              json={"category_id": seeded["dining"]})
        assert r.status_code == 200
    # a viewer is read-only: denied the write (finance.write), allowed the read.
    async with _client(_VIEWER) as client:
        r = await client.post(f"/api/finance/transactions/{tid}/categorize",
                              json={"category_id": seeded["dining"]})
        assert r.status_code == 403
        assert (await client.get("/api/finance/review-queue")).status_code == 200


@pytest.mark.asyncio
async def test_bulk_categorize(seeded):
    async with _client(_ADMIN) as client:
        r = await client.post("/api/finance/transactions/bulk-categorize",
                              json={"transaction_ids": [seeded["ids"]["a"], seeded["ids"]["b"]],
                                    "category_id": seeded["dining"]})
    assert r.status_code == 200 and r.json()["updated"] == 2


@pytest.mark.asyncio
async def test_apply_merchant_recategorizes_with_provenance(seeded):
    async with _client(_ADMIN) as client:
        r = await client.post("/api/finance/merchants/SUNRISE%20BAKERY/apply-category",
                              json={"category_id": seeded["dining"], "set_prior": True, "make_rule": True})
    assert r.status_code == 200
    body = r.json()
    assert body["updated"] == 2 and body["rule_id"] is not None
    async with seeded["pool"].acquire() as conn:
        prior = await conn.fetchval(
            "SELECT category_prior_id FROM finance.merchants WHERE merchant_key='SUNRISE BAKERY'")
        prov = await conn.fetchval(
            "SELECT count(*) FROM finance.categorization_decision "
            "WHERE rationale->>'source' = 'apply_merchant' AND applied_category_id = $1",
            seeded["dining"])
    assert prior == seeded["dining"]
    assert prov >= 2  # per-row provenance with prior_category_id


@pytest.mark.asyncio
async def test_create_user_rule_and_apply_to_existing(seeded):
    async with _client(_ADMIN) as client:
        r = await client.post("/api/finance/user-rules",
                              json={"priority": 50, "category_id": seeded["groceries"],
                                    "merchant_key": "KROGER", "apply_to_existing": True})
        assert r.status_code == 200
        body = r.json()
        assert body["rule"]["id"] is not None
        assert body["applied"] == 1  # the KROGER txn
        listed = await client.get("/api/finance/user-rules")
    assert listed.json()[0]["merchant_key"] == "KROGER"


@pytest.mark.asyncio
async def test_recurring_groups_by_merchant(seeded):
    # Add 3 same-amount charges for a new recurring merchant.
    async with seeded["pool"].acquire() as conn:
        for d in (0, 30, 60):
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, "
                "merchant_key) VALUES (gen_random_uuid()::text, $1, CURRENT_DATE - $2::int, -15.49, "
                "'NETFLIX', 'NETFLIX')", seeded["acct"], d)
    async with _client(_ADMIN) as client:
        r = await client.get("/api/finance/recurring")
    assert r.status_code == 200
    charges = {c["merchant_key"]: c for c in r.json()["charges"]}
    assert "NETFLIX" in charges
    assert charges["NETFLIX"]["occurrences"] == 3
    assert abs(charges["NETFLIX"]["avg_interval_days"] - 30.0) < 1.0


@pytest.mark.asyncio
async def test_db_down_returns_typed_503(seeded, monkeypatch):
    import backend.routers.finance_review as fr
    def boom():
        raise RuntimeError("pool not initialized")
    monkeypatch.setattr(fr, "get_pool", boom)
    async with _client(_ADMIN) as client:
        r = await client.get("/api/finance/review-queue")
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"].lower()
