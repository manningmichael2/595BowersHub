"""Two-account matrix (Task 3 / design §Test Strategy) — the headline metric.

Capabilities are seeded at their final relaxed values (0039): finance.read=viewer,
finance.write=member, finance.insight.action=member, finance.delete=admin. With
the require_capability wiring in place this test pins the actual policy:

  T-WRITE-1  member can do everyday finance writes (categorize).
  T-WRITE-2  viewer is 403 on every finance write.
  read       finance.read=viewer → member AND viewer can read.
  T-GOV-1    member + viewer are 403 on finance.delete (account-type),
             db.browser (/api/db), and users.manage (/api/admin).
  admin      passes all of the above.

Real JWTs drive the full get_current_user → live-row → authz.resolve chokepoint.
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
        JWT_SECRET="test-secret-for-the-two-account-matrix",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.finance_review import router as review
    from backend.routers.finance_accounting import router as accounting
    from backend.routers.db_browser import router as db_browser
    from backend.routers.admin import router as admin
    for r in (review, accounting, db_browser, admin):
        app.include_router(r)
    return app


async def _seed(pool: asyncpg.Pool) -> dict:
    async with pool.acquire() as conn:
        ids = {}
        for key, role in [("admin", "admin"), ("member", "member"), ("viewer", "viewer")]:
            ids[key] = await conn.fetchval(
                "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
                "VALUES ($1,'x',$2,$3) RETURNING id", f"{key}@t", key, role)
        cat_id = await conn.fetchval(
            "INSERT INTO finance.categories (name) VALUES ('Groceries') RETURNING id")
        await conn.execute("INSERT INTO finance.accounts (id, account_name) VALUES ('acct','Chk')")
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, description, source) "
            "VALUES ('tx1','acct','2026-06-01',-9,'COSTCO','simplefin')")
    return {"ids": ids, "cat_id": cat_id}


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    seed = await _seed(pool)
    auth = AuthService(pool, config)
    roles = {"admin": "admin", "member": "member", "viewer": "viewer"}
    headers = {
        k: {"Authorization": "Bearer " + auth.generate_access_token(seed["ids"][k], f"{k}@t", roles[k])}
        for k in roles
    }
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "headers": headers, "seed": seed}
        finally:
            await close_pool()


def _h(env, role):
    return env["headers"][role]


# --- T-WRITE-1 / T-WRITE-2: finance.write (member yes, viewer no) -----------
async def test_finance_write_member_yes_viewer_no(env):
    body = {"category_id": env["seed"]["cat_id"], "learn": False}
    url = "/api/finance/transactions/tx1/categorize"
    assert (await env["client"].post(url, json=body, headers=_h(env, "member"))).status_code == 200
    assert (await env["client"].post(url, json=body, headers=_h(env, "viewer"))).status_code == 403
    assert (await env["client"].post(url, json=body, headers=_h(env, "admin"))).status_code == 200


# --- finance.read=viewer: both member and viewer can read -------------------
async def test_finance_read_open_to_viewer_and_member(env):
    url = "/api/finance/categories"
    for role in ("viewer", "member", "admin"):
        assert (await env["client"].get(url, headers=_h(env, role))).status_code == 200


# --- T-GOV-1: finance.delete / db.browser / users.manage are admin-only -----
async def test_finance_delete_is_admin_only(env):
    url, body = "/api/finance/accounts/acct/type", {"account_type": "checking"}
    assert (await env["client"].put(url, json=body, headers=_h(env, "member"))).status_code == 403
    assert (await env["client"].put(url, json=body, headers=_h(env, "viewer"))).status_code == 403
    assert (await env["client"].put(url, json=body, headers=_h(env, "admin"))).status_code == 200


async def test_db_browser_is_admin_only(env):
    url = "/api/db/schemas"
    assert (await env["client"].get(url, headers=_h(env, "member"))).status_code == 403
    assert (await env["client"].get(url, headers=_h(env, "viewer"))).status_code == 403
    assert (await env["client"].get(url, headers=_h(env, "admin"))).status_code == 200


async def test_users_manage_is_admin_only(env):
    url = "/api/admin/users"
    assert (await env["client"].get(url, headers=_h(env, "member"))).status_code == 403
    assert (await env["client"].get(url, headers=_h(env, "viewer"))).status_code == 403
    assert (await env["client"].get(url, headers=_h(env, "admin"))).status_code == 200
