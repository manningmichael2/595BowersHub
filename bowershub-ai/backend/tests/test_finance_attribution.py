"""Task 5 — finance attribution (R4.1 / R4.2).

T-ATTR-1: a manual categorize stamps updated_by; a spoofed updated_by in the
  request body is rejected (extra="forbid"); the transactions list surfaces the
  editor's name; a bank-synced (NULL-attribution) row carries no editor.
T-DB-1: the schema accepts a valid-FK attribution write AND a NULL-attribution
  (system/sync) write; an invalid editor id is rejected by the FK.
"""

from __future__ import annotations

from typing import AsyncIterator

import asyncpg
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
        JWT_SECRET="test-secret-for-attribution-tests",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.finance_review import router as review_router
    from backend.routers.finance_transactions import router as txns_router
    app.include_router(review_router)
    app.include_router(txns_router)
    return app


async def _seed(pool: asyncpg.Pool) -> dict:
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('admin@t','x','Admin A','admin') RETURNING id")
        cat_id = await conn.fetchval(
            "INSERT INTO finance.categories (name) VALUES ('Groceries') RETURNING id")
        await conn.execute(
            "INSERT INTO finance.accounts (id, account_name) VALUES ('acct','Checking')")
        # An edited-by-user candidate (synced, uncategorized) and a stays-synced row.
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, source) "
            "VALUES ('tx-edit','acct','2026-06-01',-40,'COSTCO','simplefin')")
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, source) "
            "VALUES ('tx-sync','acct','2026-06-02',-12,'NETFLIX','simplefin')")
    return {"admin_id": admin_id, "cat_id": cat_id}


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    seed = await _seed(pool)
    token = AuthService(pool, config).generate_access_token(seed["admin_id"], "admin@t", "admin")
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "seed": seed,
                   "auth": {"Authorization": f"Bearer {token}"}}
        finally:
            await close_pool()


# --- T-ATTR-1 ---------------------------------------------------------------
async def test_manual_categorize_stamps_updated_by(env):
    r = await env["client"].post(
        "/api/finance/transactions/tx-edit/categorize",
        json={"category_id": env["seed"]["cat_id"], "learn": False},
        headers=env["auth"])
    assert r.status_code == 200
    async with env["pool"].acquire() as conn:
        updated_by = await conn.fetchval(
            "SELECT updated_by FROM finance.transactions WHERE id='tx-edit'")
    assert updated_by == env["seed"]["admin_id"]


async def test_updated_by_in_body_is_rejected(env):
    # extra="forbid": a smuggled updated_by must 422, never silently take effect.
    r = await env["client"].post(
        "/api/finance/transactions/tx-edit/categorize",
        json={"category_id": env["seed"]["cat_id"], "learn": False, "updated_by": 999},
        headers=env["auth"])
    assert r.status_code == 422
    async with env["pool"].acquire() as conn:
        updated_by = await conn.fetchval(
            "SELECT updated_by FROM finance.transactions WHERE id='tx-edit'")
    assert updated_by is None  # nothing was written


async def test_transactions_list_surfaces_editor_name(env):
    # Edit one row; the other stays bank-synced.
    await env["client"].post(
        "/api/finance/transactions/tx-edit/categorize",
        json={"category_id": env["seed"]["cat_id"], "learn": False},
        headers=env["auth"])
    resp = await env["client"].get("/api/finance/transactions?status=all", headers=env["auth"])
    assert resp.status_code == 200
    by_id = {it["id"]: it for it in resp.json()["items"]}
    # Edited row carries the editor's display name + the override flag.
    assert by_id["tx-edit"]["updated_by_name"] == "Admin A"
    assert by_id["tx-edit"]["user_category_override"] is True
    # Untouched row: no editor, not overridden -> the UI renders "Bank sync".
    assert by_id["tx-sync"]["updated_by_name"] is None
    assert by_id["tx-sync"]["user_category_override"] is False


# --- T-DB-1 -----------------------------------------------------------------
async def test_attribution_writes_valid_and_null(env):
    admin_id = env["seed"]["admin_id"]
    async with env["pool"].acquire() as conn:
        # Valid-FK attribution write succeeds.
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, created_by, updated_by) "
            "VALUES ('tx-attr','acct','2026-06-03',-5,$1,$1)", admin_id)
        # System/sync NULL-attribution write succeeds (D6).
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, created_by, updated_by) "
            "VALUES ('tx-null','acct','2026-06-04',-6,NULL,NULL)")
        # UPDATE to a valid editor succeeds.
        await conn.execute(
            "UPDATE finance.transactions SET updated_by=$1 WHERE id='tx-null'", admin_id)
        # An invalid editor id is rejected by the FK.
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            await conn.execute(
                "INSERT INTO finance.transactions (id, account_id, posted_date, amount, updated_by) "
                "VALUES ('tx-bad','acct','2026-06-05',-7, 999999)")
