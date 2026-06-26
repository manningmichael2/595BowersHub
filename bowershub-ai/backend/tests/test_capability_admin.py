"""Task 8 — capability/feature admin CRUD + cache invalidation.

T-NOHARDCODE-1: retune finance.write via the admin API and a member's access
  flips WITHOUT a restart (the cache is reloaded after the write); reverting
  restores the prior behavior. Proves a gate is a DB row, not a code constant.
Also: GET /capabilities + /features, role validation, and the boot self-check's
feature-registry validation.
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
        JWT_SECRET="test-secret-for-capability-admin",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.admin import router as admin
    from backend.routers.finance_review import router as review
    app.include_router(admin)
    app.include_router(review)
    return app


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
        member_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t','x','M','member') RETURNING id")
        cat_id = await conn.fetchval(
            "INSERT INTO finance.categories (name) VALUES ('Groceries') RETURNING id")
        await conn.execute("INSERT INTO finance.accounts (id, account_name) VALUES ('acct','Chk')")
        await conn.execute(
            "INSERT INTO finance.transactions (id, account_id, posted_date, amount, source) "
            "VALUES ('tx1','acct','2026-06-01',-9,'simplefin')")
    headers = {
        "admin": {"Authorization": "Bearer " + auth.generate_access_token(admin_id, "a@t", "admin")},
        "member": {"Authorization": "Bearer " + auth.generate_access_token(member_id, "m@t", "member")},
    }
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "headers": headers, "cat_id": cat_id}
        finally:
            await close_pool()


def _categorize(env, role):
    return env["client"].post("/api/finance/transactions/tx1/categorize",
                              json={"category_id": env["cat_id"], "learn": False},
                              headers=env["headers"][role])


async def test_retune_capability_flips_member_access_without_restart(env):
    # Seeded finance.write=member → member can write.
    assert (await _categorize(env, "member")).status_code == 200

    # Admin retunes finance.write → admin: the member is denied on the NEXT call,
    # with no restart (cache reloaded after the PATCH).
    r = await env["client"].patch("/api/admin/capabilities/finance.write",
                                  json={"min_role": "admin"}, headers=env["headers"]["admin"])
    assert r.status_code == 200 and r.json()["min_role"] == "admin"
    assert (await _categorize(env, "member")).status_code == 403
    assert (await _categorize(env, "admin")).status_code == 200

    # Revert → member regains access immediately.
    r2 = await env["client"].patch("/api/admin/capabilities/finance.write",
                                   json={"min_role": "member"}, headers=env["headers"]["admin"])
    assert r2.status_code == 200
    assert (await _categorize(env, "member")).status_code == 200


async def test_capabilities_and_features_listing_is_settings_write(env):
    # settings.write seeded admin → member denied, admin allowed.
    assert (await env["client"].get("/api/admin/capabilities", headers=env["headers"]["member"])).status_code == 403
    caps = await env["client"].get("/api/admin/capabilities", headers=env["headers"]["admin"])
    assert caps.status_code == 200
    by_cap = {c["capability"]: c for c in caps.json()}
    assert by_cap["finance.write"]["min_role"] == "member"

    feats = await env["client"].get("/api/admin/features", headers=env["headers"]["admin"])
    assert feats.status_code == 200
    by_feat = {f["feature_key"]: f for f in feats.json()}
    assert by_feat["database"]["admin_only_floor"] is True
    assert by_feat["finance"]["admin_only_floor"] is False


async def test_retune_rejects_unknown_role(env):
    r = await env["client"].patch("/api/admin/capabilities/finance.write",
                                  json={"min_role": "superuser"}, headers=env["headers"]["admin"])
    assert r.status_code == 400


async def test_retune_unknown_capability_404(env):
    r = await env["client"].patch("/api/admin/capabilities/does.not.exist",
                                  json={"min_role": "member"}, headers=env["headers"]["admin"])
    assert r.status_code == 404


async def test_boot_self_check_validates_feature_baseline_capability(env):
    # The 0040 FK blocks inserting a feature with an unknown baseline_capability,
    # so this guard is defense-in-depth for a cache whose baseline doesn't resolve
    # (FK bypassed/removed in a future migration). Inject directly into the warmed
    # feature cache to exercise the check.
    authz.get_features()._features["ghostfeat"] = {
        "feature_key": "ghostfeat", "label": "Ghost", "nav_routes": [],
        "baseline_capability": "ghost.capability", "admin_only_floor": False,
    }
    with pytest.raises(SystemExit) as exc:
        await authz.verify_registered_capabilities()
    assert "ghostfeat" in str(exc.value)
    # A valid registry (seeded finance/database) passes.
    del authz.get_features()._features["ghostfeat"]
    await authz.verify_registered_capabilities()
