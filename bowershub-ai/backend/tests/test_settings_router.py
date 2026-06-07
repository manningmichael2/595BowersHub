"""
Unit + RBAC tests for /api/settings/* endpoints.

End-to-end exercises ``backend.routers.settings`` against a fresh ephemeral
Postgres DB (with migrations applied and member users seeded). Uses
``httpx.AsyncClient`` with ``ASGITransport`` so the test never touches a
real network — every request is dispatched in-process to a FastAPI app
that mounts only the settings router.

Coverage (per task 12.2):
  - GET /api/settings returns ``effective_theme`` and
    ``effective_text_size`` resolved from the user's ``settings_json``,
    the platform default, and the resolver fallbacks                    (R3.2)
  - PATCH /api/settings with ``theme_id`` pointing at another user's
    private theme → 400 (theme not visible to caller)                   (R3.5)
  - PATCH /api/settings with ``text_size: "huge"`` saves the verbatim
    string but the resolver returns ``"medium"`` on read                (R4.6)
  - POST /api/settings/reset-theme clears ``settings_json.theme_id`` so
    the resolver falls back to the platform default                     (R3.7)

Validates: Requirements R3.2, R3.5, R4.6
"""

from __future__ import annotations

import json
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
        JWT_SECRET="test-secret-for-settings-router-tests",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    """Construct a minimal FastAPI app that mounts only the settings router.

    Mirrors the pattern from ``test_themes_router.py``: skips the project's
    full ``lifespan`` startup (model provider, hook engine, websocket
    manager) since none are needed for HTTP-level tests of /api/settings/*.
    The DB pool is owned by the fixture; ``init_pool`` populates the
    module-level pool that ``backend.routers.settings`` reaches via
    ``backend.database.get_pool``.
    """
    app = FastAPI()
    app.state.config = config

    from backend.routers.settings import router as settings_router

    app.include_router(settings_router)
    return app


async def _seed_users(pool: asyncpg.Pool) -> dict:
    """Create one admin + two members with distinct ids."""
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'admin')
            RETURNING id
            """,
            "admin@test.local",
            "x",
            "Admin",
        )
        user_a_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'member')
            RETURNING id
            """,
            "alice@test.local",
            "x",
            "Alice",
        )
        user_b_id = await conn.fetchval(
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
        "alice": {"id": user_a_id, "email": "alice@test.local", "role": "member"},
        "bob": {"id": user_b_id, "email": "bob@test.local", "role": "member"},
    }


@pytest_asyncio.fixture
async def settings_env(fresh_db, db_settings) -> AsyncIterator[dict]:
    """Bring up an isolated DB + app + seeded users + auth tokens.

    Yields a dict with:
      - ``client``  : ``httpx.AsyncClient`` bound to the app (in-process)
      - ``users``   : the three seeded user records
      - ``headers`` : ``{role_key: {"Authorization": "Bearer <jwt>"}}``
      - ``pool``    : the asyncpg pool (for direct DB asserts + seed helpers)
    """
    config = _make_config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)

    users = await _seed_users(pool)

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
# Helpers — DB seeders for theme rows
# ---------------------------------------------------------------------------


def _good_tokens() -> dict:
    """A high-contrast token set, shape-compatible with the validator."""
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


async def _insert_private_theme(
    pool: asyncpg.Pool,
    name: str,
    slug: str,
    owner_id: int,
) -> int:
    """Insert a private theme owned by ``owner_id`` and return its id.

    We bypass the themes router (which would assign ownership to whoever
    holds the JWT) so the test can deterministically create a theme owned
    by user_b that user_a should NOT be able to reference.
    """
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO public.bh_themes
                (name, slug, is_preset, owner_id, tokens_json)
            VALUES ($1, $2, false, $3, $4::jsonb)
            RETURNING id
            """,
            name,
            slug,
            owner_id,
            json.dumps(_good_tokens()),
        )


async def _platform_default_theme_id(pool: asyncpg.Pool) -> int:
    """Read the seeded platform default theme id (Dark Navy after migration 009)."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT value_json FROM public.bh_platform_settings
            WHERE key = 'default_theme_id'
            """
        )
    assert row is not None, "default_theme_id missing — migration 009 broken"
    theme_id = (row["value_json"] or {}).get("theme_id")
    assert isinstance(theme_id, int), (
        f"default_theme_id must be an int, got {theme_id!r}"
    )
    return theme_id


async def _user_settings_json(pool: asyncpg.Pool, user_id: int) -> dict:
    """Read the persisted settings_json for a user — used to verify writes."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT settings_json FROM public.bh_users WHERE id = $1",
            user_id,
        )
    assert row is not None
    value = row["settings_json"]
    return value if isinstance(value, dict) else {}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_get_returns_effective_theme_and_text_size(settings_env):
    """GET /api/settings returns the resolved effects for a fresh user (R3.2).

    A user with empty ``settings_json`` falls through to the platform
    default theme (Dark Navy preset, seeded by migration 009) and the
    text-size resolver default (``medium``). Asserts the response carries
    both ``effective_theme`` and ``effective_text_size`` and that
    ``effective_theme.id`` matches the platform default seeded in the DB.
    """
    client = settings_env["client"]
    pool = settings_env["pool"]

    expected_default_id = await _platform_default_theme_id(pool)

    resp = await client.get(
        "/api/settings", headers=settings_env["headers"]["alice"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Settings blob is exposed verbatim — empty dict for a fresh user.
    assert body["settings"] == {}, (
        f"fresh user should have empty settings_json, got {body['settings']!r}"
    )

    # Effective theme — full shape with the resolved row.
    assert "effective_theme" in body, body
    effective_theme = body["effective_theme"]
    assert effective_theme["id"] == expected_default_id, (
        f"effective_theme.id should match platform default "
        f"({expected_default_id}), got {effective_theme['id']!r}"
    )
    assert effective_theme["slug"] == "dark-navy"
    assert effective_theme["is_default"] is True
    # tokens_json is the actual palette — verify the canonical keys are present.
    tokens = effective_theme["tokens_json"]
    for key in (
        "background",
        "surface",
        "primary",
        "accent",
        "text",
        "text_muted",
        "border",
        "danger",
        "success",
    ):
        assert key in tokens, f"missing token {key!r} in {tokens!r}"

    # Effective text size — resolver default is the canonical 'medium' label.
    assert body["effective_text_size"] == "medium", (
        f"empty settings_json should resolve to 'medium', got "
        f"{body['effective_text_size']!r}"
    )


async def test_patch_theme_id_to_other_users_private_theme_returns_400(settings_env):
    """PATCH theme_id pointing at another user's private theme → 400 (R3.5).

    Bob creates a private theme. Alice tries to set ``theme_id`` to
    Bob's theme via PATCH. The router queries the visible-themes view
    for Alice (presets + admin-published + own) — which doesn't
    include Bob's private theme — and rejects the patch with HTTP 400.

    Round-trip assertion: Alice's settings_json was NOT modified, so the
    rejection happened before any write.
    """
    client = settings_env["client"]
    pool = settings_env["pool"]
    alice = settings_env["users"]["alice"]
    bob = settings_env["users"]["bob"]

    bob_theme_id = await _insert_private_theme(
        pool, "Bob's Private", "bobs-private", owner_id=bob["id"]
    )

    resp = await client.patch(
        "/api/settings",
        json={"theme_id": bob_theme_id},
        headers=settings_env["headers"]["alice"],
    )
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert "not visible" in detail.lower(), (
        f"expected 'not visible' in detail, got {detail!r}"
    )

    # Round-trip: Alice's settings_json should be untouched.
    persisted = await _user_settings_json(pool, alice["id"])
    assert persisted == {}, (
        f"settings_json should not have been written on a 400, got {persisted!r}"
    )


async def test_patch_unknown_text_size_persists_value_resolver_returns_medium(
    settings_env,
):
    """PATCH text_size='huge' saves the value but resolver returns medium (R4.6).

    Per design.md and ``text_size_resolver.resolve``, any string outside
    the four canonical labels (``small``, ``medium``, ``large``,
    ``extra_large``) — including ``"huge"`` — should resolve to
    ``("medium", 1.0)``. The router persists the user's literal string
    in ``settings_json`` so we don't lose it on round-trip, but the
    derived ``effective_text_size`` always returns the canonical label.
    """
    client = settings_env["client"]
    pool = settings_env["pool"]
    alice = settings_env["users"]["alice"]

    resp = await client.patch(
        "/api/settings",
        json={"text_size": "huge"},
        headers=settings_env["headers"]["alice"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The literal value survives in the settings blob.
    assert body["settings"].get("text_size") == "huge", (
        f"unknown text_size should be persisted verbatim, got "
        f"settings={body['settings']!r}"
    )
    # …but the resolver maps it to 'medium'.
    assert body["effective_text_size"] == "medium", (
        f"unknown text_size should resolve to 'medium', got "
        f"{body['effective_text_size']!r}"
    )

    # Round-trip via DB: same expectation.
    persisted = await _user_settings_json(pool, alice["id"])
    assert persisted.get("text_size") == "huge", (
        f"DB-side settings_json should have text_size='huge', got {persisted!r}"
    )


async def test_reset_theme_clears_override_and_falls_back_to_platform_default(
    settings_env,
):
    """POST /api/settings/reset-theme clears the user's theme_id (R3.7).

    Alice sets ``theme_id`` to a preset (light-stone, visible to all)
    via PATCH; the resolver returns that theme. POST /reset-theme then
    removes the override so the resolver falls back to the platform
    default (dark-navy, seeded by migration 009). Asserts:
      - the override key is gone from settings_json
      - effective_theme.id matches the platform default again
      - the call is idempotent: a second reset-theme is a no-op write
    """
    client = settings_env["client"]
    pool = settings_env["pool"]
    alice = settings_env["users"]["alice"]

    # Pick a preset other than the platform default so the override is
    # observable in the response.
    async with pool.acquire() as conn:
        light_stone_id = await conn.fetchval(
            """
            SELECT id FROM public.bh_themes
            WHERE slug = 'light-stone' AND owner_id IS NULL
            """
        )
    assert light_stone_id is not None, (
        "light-stone preset missing — migration 009 broken"
    )
    platform_default_id = await _platform_default_theme_id(pool)
    assert light_stone_id != platform_default_id, (
        "light-stone unexpectedly is the platform default; pick another preset"
    )

    # 1. Set the override.
    patch_resp = await client.patch(
        "/api/settings",
        json={"theme_id": light_stone_id},
        headers=settings_env["headers"]["alice"],
    )
    assert patch_resp.status_code == 200, patch_resp.text
    assert patch_resp.json()["effective_theme"]["id"] == light_stone_id

    persisted = await _user_settings_json(pool, alice["id"])
    assert persisted.get("theme_id") == light_stone_id

    # 2. Reset.
    reset_resp = await client.post(
        "/api/settings/reset-theme", headers=settings_env["headers"]["alice"]
    )
    assert reset_resp.status_code == 200, reset_resp.text
    body = reset_resp.json()

    # The settings_json no longer carries theme_id.
    assert "theme_id" not in body["settings"], (
        f"reset-theme must drop theme_id key, got settings={body['settings']!r}"
    )
    # The router signals the cleared override per design.
    assert body.get("theme_id") is None
    # Resolver falls back to the platform default.
    assert body["effective_theme"]["id"] == platform_default_id, (
        f"effective_theme should fall back to platform default "
        f"({platform_default_id}), got {body['effective_theme']['id']!r}"
    )

    persisted_after = await _user_settings_json(pool, alice["id"])
    assert "theme_id" not in persisted_after, (
        f"DB-side settings_json should have theme_id removed, got "
        f"{persisted_after!r}"
    )

    # 3. Idempotency: second reset is a clean 200 with the same shape.
    reset_again = await client.post(
        "/api/settings/reset-theme", headers=settings_env["headers"]["alice"]
    )
    assert reset_again.status_code == 200, reset_again.text
    assert reset_again.json()["effective_theme"]["id"] == platform_default_id
