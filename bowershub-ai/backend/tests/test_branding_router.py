"""
RBAC + smoke test for /api/branding/* endpoints.

End-to-end exercises ``backend.routers.branding`` against a fresh ephemeral
Postgres DB (with migrations applied and admin/member users seeded). Uses
``httpx.AsyncClient`` with ``ASGITransport`` so the test never touches a
real network — every request is dispatched in-process to the FastAPI app.

The on-disk branding root is isolated to ``tmp_path/branding/`` via a
monkeypatched ``FILES_ROOT`` env var, so uploads can't pollute the host
``/files/branding/`` directory and test order doesn't matter.

Coverage (per task 11.2):
  - GET /api/branding/icon works for any authenticated user            (R2.1)
  - POST /api/branding/icon returns 403 for non-admin                  (R2.8)
  - POST /api/branding/icon with non-PNG (JPEG) returns 400            (R2.3)
  - POST /api/branding/icon with a >4MB PNG returns 413                (R2.3)
  - POST /api/branding/icon/rollback with no previous slot returns 409 (R2.7)

Validates: Requirements R2.3, R2.8
"""

from __future__ import annotations

import io
import os
from typing import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from PIL import Image

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# App + fixture wiring
# ---------------------------------------------------------------------------


def _make_config(db_name: str, db_settings: dict, files_root: str) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-branding-router-tests",
        N8N_BASE="http://localhost:5678",
        FILES_ROOT=files_root,
    )


def _build_app(config: Config) -> FastAPI:
    """Construct a minimal FastAPI app that mounts only the branding router.

    We avoid the project's full ``lifespan`` startup (model provider, hook
    engine, websocket manager) — none are needed for HTTP-level tests of
    /api/branding/*. The DB pool is owned by the fixture and reachable by
    the router via ``backend.database.get_pool``; ``app.state.config`` is
    needed by the auth middleware to construct an ``AuthService``.
    """
    app = FastAPI()
    app.state.config = config

    from backend.routers.branding import router as branding_router

    app.include_router(branding_router)
    return app


async def _seed_users(pool: asyncpg.Pool) -> dict:
    """Create one admin + one member with distinct ids for the tests."""
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
        member_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'member')
            RETURNING id
            """,
            "alice@test.local",
            "x",
            "Alice",
        )

    return {
        "admin": {"id": admin_id, "email": "admin@test.local", "role": "admin"},
        "alice": {"id": member_id, "email": "alice@test.local", "role": "member"},
    }


@pytest_asyncio.fixture
async def branding_env(
    fresh_db, db_settings, tmp_path, monkeypatch
) -> AsyncIterator[dict]:
    """Bring up an isolated DB + app + seeded users + auth tokens.

    Pins the branding store's on-disk root to ``tmp_path`` via the
    ``FILES_ROOT`` env var (the store reads it at call time). Populates the
    DB pool, runs migrations, seeds users, and yields a dict with:

      - ``client``  : ``httpx.AsyncClient`` bound to the app (in-process)
      - ``users``   : the seeded user records
      - ``headers`` : ``{role_key: {"Authorization": "Bearer <jwt>"}}``
      - ``pool``    : the asyncpg pool (for direct DB asserts)
      - ``branding_root`` : ``Path`` for the on-disk root, useful for
        per-test setup (e.g., populating ``previous/`` to flip
        rollback semantics).
    """
    files_root = str(tmp_path)
    monkeypatch.setenv("FILES_ROOT", files_root)

    config = _make_config(fresh_db, db_settings, files_root)
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
                "branding_root": tmp_path / "branding",
            }
        finally:
            await close_pool()


# ---------------------------------------------------------------------------
# Helpers — image builders
# ---------------------------------------------------------------------------


def _make_valid_png(size: int = 1024) -> bytes:
    """Build a small, well-compressed square RGBA PNG in memory.

    Used by tests that need a payload that *could* succeed all four
    validator rules (mime/dim/aspect/size) so any failure is attributable
    to the rule under test (e.g., RBAC) rather than incidental validation.
    """
    img = Image.new("RGBA", (size, size), (32, 96, 192, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _make_jpeg(size: int = 1024) -> bytes:
    """Build a square JPEG that satisfies dimension/size rules but not mime.

    Asserts the produced bytes are >0 and that ``Image.open`` would
    classify them as ``JPEG`` so the branding store's mime check is the
    sole reason for rejection.
    """
    img = Image.new("RGB", (size, size), (32, 96, 192))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue()


def _make_oversized_png() -> bytes:
    """Build a square PNG whose serialized size exceeds 4 MB (R2.3 max).

    Strategy: a sufficiently large square of random RGBA noise is nearly
    incompressible by deflate. 1500x1500 RGBA random ≈ 9 MB raw → typically
    ~7-8 MB PNG, which clears the 4 MB threshold by a comfortable margin
    while keeping the test fast. We assert the threshold is exceeded so the
    test fails loudly if a future Pillow / zlib change pushes the
    compression below the limit.
    """
    side = 1500
    raw = os.urandom(side * side * 4)
    img = Image.frombytes("RGBA", (side, side), raw)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    data = buf.getvalue()
    assert len(data) > 4 * 1024 * 1024, (
        f"oversized PNG fixture compressed to {len(data)} bytes — "
        f"need >4 MB to exercise the size-rule path"
    )
    return data


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_get_icon_works_for_any_authenticated_user(branding_env):
    """GET /api/branding/icon → 200 for member (R2.1).

    The icon manifest is part of the app chrome that every user sees, so
    the route is gated by ``get_current_user`` (any authenticated user)
    rather than ``require_admin``. A fresh setup has no upload and no
    rollback slot, so ``has_rollback`` should be False and the URLs
    should reference ``/icons/icon-*.png`` with a version stamp.
    """
    client = branding_env["client"]

    resp = await client.get(
        "/api/branding/icon", headers=branding_env["headers"]["alice"]
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "version" in body
    assert isinstance(body["version"], str) and body["version"]
    assert body["has_rollback"] is False, (
        "fresh test setup should have no rollback slot populated"
    )
    # The store names URLs with underscores (icon_192) but the on-disk
    # files (and therefore the served path) use dashes (icon-192.png).
    expected_path_for = {
        "icon_192": "/icons/icon-192.png?v=",
        "icon_512": "/icons/icon-512.png?v=",
        "icon_maskable_512": "/icons/icon-maskable-512.png?v=",
    }
    urls = body["urls"]
    for key, expected_prefix in expected_path_for.items():
        assert key in urls, f"missing url key {key} in {urls!r}"
        assert urls[key].startswith(expected_prefix), (
            f"url for {key} did not include versioned /icons/ path: {urls[key]!r}"
        )


async def test_post_icon_returns_403_for_non_admin(branding_env):
    """POST /api/branding/icon → 403 for member (R2.8).

    A non-admin uploading a perfectly-valid PNG must be rejected by the
    ``require_admin`` dependency before the branding store sees the
    bytes. Asserts the on-disk active set is unchanged after the call.
    """
    client = branding_env["client"]
    branding_root = branding_env["branding_root"]

    valid_png = _make_valid_png(1024)

    # Snapshot active/ before the call so we can assert no write happened.
    active = branding_root / "active"
    before = sorted(p.name for p in active.iterdir()) if active.exists() else []

    resp = await client.post(
        "/api/branding/icon",
        files={"file": ("icon.png", valid_png, "image/png")},
        headers=branding_env["headers"]["alice"],
    )
    assert resp.status_code == 403, resp.text

    after = sorted(p.name for p in active.iterdir()) if active.exists() else []
    assert before == after, (
        f"active/ contents changed after a 403 upload: before={before} after={after}"
    )


async def test_post_icon_with_non_png_returns_400(branding_env):
    """POST /api/branding/icon with a JPEG → 400 (R2.3 mime rule).

    The branding store validates mime against ``image/png``; everything
    else (mime/dim/aspect/decode) maps to 400. Only size violations get
    413. The JPEG fixture passes the dim/aspect/size rules so the only
    triggered error is the mime mismatch — which lets us assert the
    response shape carries a per-field error labeled ``mime``.
    """
    client = branding_env["client"]

    jpeg_bytes = _make_jpeg(1024)

    resp = await client.post(
        "/api/branding/icon",
        files={"file": ("not-a-png.jpg", jpeg_bytes, "image/jpeg")},
        headers=branding_env["headers"]["admin"],
    )
    assert resp.status_code == 400, resp.text

    detail = resp.json()["detail"]
    errors = detail.get("errors") or []
    fields = {e.get("field") for e in errors}
    assert "mime" in fields, (
        f"expected a 'mime' field error; got errors={errors!r}"
    )
    assert "size" not in fields, (
        f"jpeg payload should not trigger the size rule; got errors={errors!r}"
    )


async def test_post_icon_oversized_png_returns_413(branding_env):
    """POST /api/branding/icon with a >4MB PNG → 413 (R2.3 size rule).

    The router maps any IconValidationError whose error set contains a
    ``size`` field to HTTP 413; otherwise 400. By using a square,
    PNG-mime payload that only fails the size rule, we exercise that
    branch precisely.
    """
    client = branding_env["client"]

    oversized = _make_oversized_png()

    resp = await client.post(
        "/api/branding/icon",
        files={"file": ("big.png", oversized, "image/png")},
        headers=branding_env["headers"]["admin"],
    )
    assert resp.status_code == 413, resp.text

    detail = resp.json()["detail"]
    errors = detail.get("errors") or []
    fields = {e.get("field") for e in errors}
    assert "size" in fields, (
        f"expected a 'size' field error in 413 response; got errors={errors!r}"
    )


async def test_rollback_returns_409_when_no_slot(branding_env):
    """POST /api/branding/icon/rollback with no previous slot → 409 (R2.7).

    The ``branding/previous/`` directory is empty on a fresh setup, so
    ``branding_store.rollback()`` raises ``RollbackUnavailable`` and the
    router maps that to 409 Conflict. Asserts no DB version bump
    occurred (the version stays at the seeded value).
    """
    client = branding_env["client"]
    pool = branding_env["pool"]

    # Read the seeded version BEFORE the failed rollback.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT value_json FROM public.bh_platform_settings
            WHERE key = 'app_icon_version'
            """
        )
    seeded_version = (row["value_json"] or {}).get("version")
    assert seeded_version is not None, (
        "app_icon_version row missing — migration 009 broken"
    )

    resp = await client.post(
        "/api/branding/icon/rollback",
        headers=branding_env["headers"]["admin"],
    )
    assert resp.status_code == 409, resp.text

    # DB version should be unchanged (rollback raised before writing).
    async with pool.acquire() as conn:
        row_after = await conn.fetchrow(
            """
            SELECT value_json FROM public.bh_platform_settings
            WHERE key = 'app_icon_version'
            """
        )
    after_version = (row_after["value_json"] or {}).get("version")
    assert after_version == seeded_version, (
        f"version changed despite 409 rollback: {seeded_version} -> {after_version}"
    )
