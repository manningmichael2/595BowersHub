"""
RBAC + smoke test for /api/themes/* endpoints.

End-to-end exercises ``backend.routers.themes`` against a fresh ephemeral
Postgres DB (with migrations applied and admin/member users seeded). Uses
``httpx.AsyncClient`` with ``ASGITransport`` so the test never touches a
real network — every request is dispatched in-process to the FastAPI app.

Coverage (per task 10.2):
  - admin creates a published theme (owner_id IS NULL)                   (R1.5)
  - member creates a personal theme (owner_id = self)                    (R3.5)
  - member tries to PATCH another member's theme → 403                   (R3.5)
  - member tries to POST with publish=true → 403                         (R1.10)
  - admin sets a preset as the platform default → 200                    (R1.3)
  - admin tries to DELETE a preset theme → 409                           (R1.5)
  - tokens that block contrast (text/background ratio < 2.0) → 422       (R1.8)

Validates: Requirements R1.5, R1.8, R1.10, R3.5
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


# ---------------------------------------------------------------------------
# App + fixture wiring
# ---------------------------------------------------------------------------


def _make_config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-themes-router-tests",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    """Construct a minimal FastAPI app that mounts only the themes router.

    We avoid the project's full ``lifespan`` startup (model provider,
    hook engine, websocket manager) — none are needed for HTTP-level
    tests of /api/themes/*. The DB pool is owned by the fixture and
    attached as ``app.state.pool``; ``init_pool`` already populates the
    module-level pool that ``backend.routers.themes`` reaches via
    ``backend.database.get_pool``.
    """
    app = FastAPI()
    app.state.config = config

    from backend.routers.themes import router as themes_router

    app.include_router(themes_router)
    return app


async def _seed_users(pool: asyncpg.Pool) -> dict:
    """Create one admin + two members with distinct ids for the tests."""
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'admin')
            RETURNING id
            """,
            "admin@test.local",
            "x",  # placeholder — we never call AuthService.authenticate()
            "Admin",
        )
        member_a_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'member')
            RETURNING id
            """,
            "alice@test.local",
            "x",
            "Alice",
        )
        member_b_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'member')
            RETURNING id
            """,
            "bob@test.local",
            "x",
            "Bob",
        )

    return {
        "admin": {"id": admin_id, "email": "admin@test.local", "role": "admin"},
        "alice": {"id": member_a_id, "email": "alice@test.local", "role": "member"},
        "bob": {"id": member_b_id, "email": "bob@test.local", "role": "member"},
    }


@pytest_asyncio.fixture
async def themes_env(fresh_db, db_settings) -> AsyncIterator[dict]:
    """Bring up an isolated DB + app + seeded users + auth tokens.

    Yields a dict with:
      - ``client``  : ``httpx.AsyncClient`` bound to the app (in-process)
      - ``users``   : the three seeded user records
      - ``headers`` : ``{role_key: {"Authorization": "Bearer <jwt>"}}``
      - ``pool``    : the asyncpg pool (for direct DB asserts)
    """
    config = _make_config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)

    users = await _seed_users(pool)

    # Mint JWTs against the same Config used by the app's auth middleware.
    from backend.services.auth import AuthService

    auth = AuthService(pool, config)
    headers = {
        role: {
            "Authorization": "Bearer "
            + auth.generate_access_token(u["id"], u["email"], u["role"]),
        }
        for role, u in users.items()
    }

    app = _build_app(config)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield {
                "client": client,
                "users": users,
                "headers": headers,
                "pool": pool,
            }
        finally:
            await close_pool()


# ---------------------------------------------------------------------------
# Helpers — payload builders
# ---------------------------------------------------------------------------


def _good_tokens() -> dict:
    """A high-contrast token set guaranteed to clear the 4.5:1 contrast bar."""
    return {
        "background": "#ffffff",
        "surface": "#f5f5f5",
        "primary": "#4f46e5",
        "accent": "#6366f1",
        "text": "#000000",
        "text_muted": "#555555",
        "border": "#dddddd",
        "danger": "#dc2626",
        "success": "#16a34a",
    }


def _block_contrast_tokens() -> dict:
    """Text/background pair with contrast ratio well below 2.0:1.

    White-on-near-white: text=#fafafa, background=#ffffff → ratio ≈ 1.05.
    The validator must reject this with HTTP 422 (R1.8).
    """
    tokens = _good_tokens()
    tokens["background"] = "#ffffff"
    tokens["text"] = "#fafafa"
    return tokens


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_admin_create_published_theme_persists_with_owner_id_null(themes_env):
    """Admin POSTs with publish=true → 201, owner_id=NULL (R1.5)."""
    client = themes_env["client"]
    pool = themes_env["pool"]

    resp = await client.post(
        "/api/themes",
        json={"name": "Admin Brand", "tokens_json": _good_tokens(), "publish": True},
        headers=themes_env["headers"]["admin"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["owner_id"] is None, (
        f"published theme should have owner_id=NULL, got {body['owner_id']}"
    )
    assert body["is_preset"] is False
    assert body["name"] == "Admin Brand"

    # DB sanity: row exists with the expected shape.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT owner_id, is_preset FROM public.bh_themes WHERE id = $1",
            body["id"],
        )
    assert row["owner_id"] is None
    assert row["is_preset"] is False


async def test_member_create_personal_theme_owns_it(themes_env):
    """Member POSTs without publish → 201, owner_id=self (R3.5)."""
    client = themes_env["client"]
    alice = themes_env["users"]["alice"]

    resp = await client.post(
        "/api/themes",
        json={"name": "Alice's Theme", "tokens_json": _good_tokens()},
        headers=themes_env["headers"]["alice"],
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["owner_id"] == alice["id"], (
        f"personal theme should have owner_id={alice['id']}, got {body['owner_id']}"
    )


async def test_member_cannot_publish_returns_403(themes_env):
    """Non-admin sending publish=true → 403, no row written (R1.10)."""
    client = themes_env["client"]
    pool = themes_env["pool"]

    resp = await client.post(
        "/api/themes",
        json={
            "name": "Sneaky Publish",
            "tokens_json": _good_tokens(),
            "publish": True,
        },
        headers=themes_env["headers"]["alice"],
    )
    assert resp.status_code == 403, resp.text

    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM public.bh_themes WHERE name = $1",
            "Sneaky Publish",
        )
    assert count == 0, "non-admin publish should not have inserted a row"


async def test_member_cannot_patch_other_members_theme_returns_403(themes_env):
    """Bob PATCHing Alice's personal theme → 403 (R3.5)."""
    client = themes_env["client"]

    # Alice creates a personal theme.
    create = await client.post(
        "/api/themes",
        json={"name": "Alice's Private", "tokens_json": _good_tokens()},
        headers=themes_env["headers"]["alice"],
    )
    assert create.status_code == 201, create.text
    theme_id = create.json()["id"]

    # Bob tries to rename it.
    resp = await client.patch(
        f"/api/themes/{theme_id}",
        json={"name": "Hijacked"},
        headers=themes_env["headers"]["bob"],
    )
    assert resp.status_code == 403, resp.text

    # Round-trip: name didn't change.
    pool = themes_env["pool"]
    async with pool.acquire() as conn:
        name = await conn.fetchval(
            "SELECT name FROM public.bh_themes WHERE id = $1", theme_id
        )
    assert name == "Alice's Private"


async def test_admin_sets_preset_as_platform_default_returns_200(themes_env):
    """Admin POST /set-platform-default on a preset → 200 (R1.3)."""
    client = themes_env["client"]
    pool = themes_env["pool"]

    # Find a preset that's not currently the default. Migration 009 seeds
    # dark-navy as the default, so pick light-stone.
    async with pool.acquire() as conn:
        light_stone_id = await conn.fetchval(
            """
            SELECT id FROM public.bh_themes
            WHERE slug = 'light-stone' AND owner_id IS NULL
            """
        )
    assert light_stone_id is not None, "light-stone preset missing — migration 009 broken"

    resp = await client.post(
        f"/api/themes/{light_stone_id}/set-platform-default",
        headers=themes_env["headers"]["admin"],
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True, "theme_id": light_stone_id}

    # Round-trip: the platform default pointer now references this theme.
    async with pool.acquire() as conn:
        default_row = await conn.fetchrow(
            """
            SELECT value_json FROM public.bh_platform_settings
            WHERE key = 'default_theme_id'
            """
        )
    assert default_row is not None
    assert default_row["value_json"]["theme_id"] == light_stone_id


async def test_admin_delete_preset_returns_409(themes_env):
    """DELETE on an `is_preset=true` row → 409 (R1.5: presets are undeletable)."""
    client = themes_env["client"]
    pool = themes_env["pool"]

    async with pool.acquire() as conn:
        preset_id = await conn.fetchval(
            """
            SELECT id FROM public.bh_themes
            WHERE slug = 'mono' AND owner_id IS NULL
            """
        )
    assert preset_id is not None

    resp = await client.delete(
        f"/api/themes/{preset_id}", headers=themes_env["headers"]["admin"]
    )
    assert resp.status_code == 409, resp.text

    # Row should still be present.
    async with pool.acquire() as conn:
        still_there = await conn.fetchval(
            "SELECT count(*) FROM public.bh_themes WHERE id = $1", preset_id
        )
    assert still_there == 1


async def test_contrast_block_returns_422(themes_env):
    """text/background contrast < 2.0:1 → 422 (R1.8)."""
    client = themes_env["client"]
    pool = themes_env["pool"]

    resp = await client.post(
        "/api/themes",
        json={
            "name": "Unreadable Theme",
            "tokens_json": _block_contrast_tokens(),
        },
        headers=themes_env["headers"]["admin"],
    )
    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert detail.get("contrast") == "block", (
        f"expected detail.contrast='block', got {detail!r}"
    )

    # No row should have been written.
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT count(*) FROM public.bh_themes WHERE name = $1",
            "Unreadable Theme",
        )
    assert count == 0
