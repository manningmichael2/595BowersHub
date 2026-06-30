"""Lists v2 — Task 6/8: item→list routing (decision logic, default, degradation, skill)."""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import list_router, list_config
from backend.services import lists as svc

pytestmark = pytest.mark.asyncio


# ── Pure decision logic (no DB / no model) ────────────────────────────────────

CFG = {"match_threshold": 0.55, "create_threshold": 0.35, "ambiguity_margin": 0.07}


def test_decide_match():
    d = list_router._decide([{"id": 1, "name": "g", "sim": 0.8},
                             {"id": 2, "name": "t", "sim": 0.4}], CFG)
    assert d["action"] == "match" and d["list"]["id"] == 1


def test_decide_disambiguate_when_close():
    d = list_router._decide([{"id": 1, "name": "g", "sim": 0.80},
                             {"id": 2, "name": "t", "sim": 0.78}], CFG)
    assert d["action"] == "disambiguate" and len(d["candidates"]) == 2


def test_decide_fallback_below_threshold():
    d = list_router._decide([{"id": 1, "name": "g", "sim": 0.30}], CFG)
    assert d["action"] == "fallback"
    assert list_router._decide([], CFG)["action"] == "fallback"


# ── DB-backed deterministic paths ─────────────────────────────────────────────

def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-router", N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    pool = await init_pool(_config(fresh_db, db_settings))
    await run_migrations(pool)
    async with pool.acquire() as conn:
        uid = await conn.fetchval(
            "INSERT INTO public.bh_users (email,password_hash,display_name,role) "
            "VALUES ('mi@t','x','Michael','admin') RETURNING id")
    try:
        yield {"pool": pool, "uid": uid}
    finally:
        await close_pool()


async def test_ensure_default_lazily_creates_shopping(env):
    async with env["pool"].acquire() as conn:
        # Fresh DB: no default elected.
        assert await list_config.get_default_list_id(conn) is None
        lid = await list_router.ensure_default_list(conn, env["uid"])
        assert lid is not None
        # It persisted as the default and is named 'Shopping'.
        assert await list_config.get_default_list_id(conn) == lid
        name = await conn.fetchval("SELECT name FROM public.bh_lists WHERE id=$1", lid)
        assert name == "Shopping"
        # Idempotent: a second call reuses it.
        assert await list_router.ensure_default_list(conn, env["uid"]) == lid


async def test_route_item_no_embedder_uses_default(env):
    async with env["pool"].acquire() as conn:
        routed = await list_router.route_item(conn, "milk", env["uid"], embedder=None)
        assert routed.get("fallback") is True
        assert routed["list_id"] == await list_config.get_default_list_id(conn)


async def test_route_item_degrades_when_embedder_raises(env):
    async def broken(_text):
        from backend.services.embeddings import EmbeddingError
        raise EmbeddingError("ollama down")
    async with env["pool"].acquire() as conn:
        routed = await list_router.route_item(conn, "milk", env["uid"], embedder=broken)
        # Never raises/drops — falls back to the default list.
        assert routed["list_id"] is not None


async def test_skill_add_routes_to_explicit_list_no_junk(env):
    # Create a real 'gifts' list; explicit add lands there.
    async with env["pool"].acquire() as conn:
        gid = await svc.create_list(conn, "Gifts", env["uid"])
    out = await list_router.route_and_add(["socks"], env["uid"], explicit_list="Gifts")
    assert out["added"][0]["list_id"] == gid
    # An UNRESOLVED explicit name does NOT create a junk list — item goes to default.
    out2 = await list_router.route_and_add(["milk"], env["uid"], explicit_list="nonexistent")
    async with env["pool"].acquire() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM public.bh_lists WHERE LOWER(name)='nonexistent'") == 0
        default_id = await list_config.get_default_list_id(conn)
    assert out2["added"][0]["list_id"] == default_id
