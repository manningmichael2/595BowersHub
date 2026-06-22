"""
Tests for /api/telemetry/* (client error reporting).

Exercises ``backend.routers.telemetry`` against a fresh ephemeral Postgres DB
via ``httpx.AsyncClient`` + ``ASGITransport`` (in-process, no network). Pushover
is a no-op here (no creds configured), so the rate-limit branch is exercised
without sending anything.

Coverage:
  - POST /api/telemetry/client-error (authed) stores a row + returns ok
  - GET /api/telemetry/client-errors requires admin (member → 403)
  - GET returns recent errors for the admin
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


pytestmark = pytest.mark.asyncio


def _make_config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-telemetry-router-tests",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.telemetry import router as telemetry_router

    app.include_router(telemetry_router)
    return app


async def _seed_users(pool: asyncpg.Pool) -> dict:
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'admin') RETURNING id
            """,
            "admin@test.local", "x", "Admin",
        )
        member_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'member') RETURNING id
            """,
            "alice@test.local", "x", "Alice",
        )
    return {
        "admin": {"id": admin_id, "email": "admin@test.local", "role": "admin"},
        "member": {"id": member_id, "email": "alice@test.local", "role": "member"},
    }


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _make_config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    users = await _seed_users(pool)

    from backend.services.auth import AuthService

    auth = AuthService(pool, config)
    headers = {
        role: {"Authorization": "Bearer " + auth.generate_access_token(u["id"], u["email"], u["role"])}
        for role, u in users.items()
    }

    app = _build_app(config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield {"client": client, "users": users, "headers": headers, "pool": pool}
        finally:
            await close_pool()


async def test_post_stores_a_client_error(env):
    resp = await env["client"].post(
        "/api/telemetry/client-error",
        json={"message": "TypeError: x is undefined", "stack": "at f (a.js:1:2)", "url": "http://test/chat"},
        headers=env["headers"]["member"],
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    async with env["pool"].acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM public.bh_client_errors ORDER BY id DESC LIMIT 1")
    assert row["message"] == "TypeError: x is undefined"
    assert row["user_id"] == env["users"]["member"]["id"]
    assert row["signature"]  # computed


async def test_post_requires_auth(env):
    resp = await env["client"].post(
        "/api/telemetry/client-error", json={"message": "boom"}
    )
    assert resp.status_code == 401


async def test_list_requires_admin(env):
    # Seed one error as the member.
    await env["client"].post(
        "/api/telemetry/client-error", json={"message": "boom"}, headers=env["headers"]["member"]
    )

    member_resp = await env["client"].get("/api/telemetry/client-errors", headers=env["headers"]["member"])
    assert member_resp.status_code == 403

    admin_resp = await env["client"].get("/api/telemetry/client-errors", headers=env["headers"]["admin"])
    assert admin_resp.status_code == 200
    errors = admin_resp.json()["errors"]
    assert any(e["message"] == "boom" for e in errors)
