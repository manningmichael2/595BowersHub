"""
RBAC + smoke test for workspace `system_prompt` and pinned-context refresh.

End-to-end exercises the extensions to ``backend.routers.workspaces`` against
a fresh ephemeral Postgres DB (with all migrations applied and admin/member/
non-member users plus a workspace and pinned-context entries seeded).
Uses ``httpx.AsyncClient`` with ``ASGITransport`` so the test never touches a
real network — every request is dispatched in-process to a FastAPI app that
mounts only the workspaces router.

Coverage (per task 13.3):
  - PATCH with a 60,000-char ``system_prompt`` → 400 length-limit error  (R6.6)
  - Non-admin PATCH with ``system_prompt`` in body → 403                 (R6.8)
  - Member GET on workspace returns 200 with the ``system_prompt``       (R5.6)
  - POST refresh on a ``type='static'`` pinned-context entry → 400       (R7.7)
  - POST refresh on a ``type='dynamic'`` entry → 200 with updated cache  (R7.7, R7.9)

Validates: Requirements R5.6, R6.6, R6.8, R7.7, R7.9
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

_ORIGINAL_PROMPT = "You are a helpful workshop assistant."


def _make_config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-workspaces-router-tests",
        N8N_BASE="http://localhost:5678",
    )


def _build_app(config: Config) -> FastAPI:
    """Construct a minimal FastAPI app that mounts only the workspaces router.

    Like ``test_themes_router``, we skip the project's full ``lifespan``
    startup (model provider, hook engine, websocket manager) — none are
    needed for HTTP-level tests of /api/workspaces/*. The DB pool is owned
    by the fixture; ``init_pool`` populates the module-level pool that
    ``backend.routers.workspaces`` reaches via ``backend.database.get_pool``.
    """
    app = FastAPI()
    app.state.config = config

    from backend.routers.workspaces import router as workspaces_router

    app.include_router(workspaces_router)
    return app


async def _seed_world(pool: asyncpg.Pool) -> dict:
    """Seed admin + member + outsider users, a workspace, and two pinned
    contexts (one static, one dynamic).

    Layout:
      * admin    — global admin
      * alice    — workspace member
      * bob      — non-member outsider (currently unused by these tests but
                   kept for symmetry with the themes test pattern)

    The workspace's ``permitted_schemas`` includes ``public`` so the
    SchemaGuard validator allows queries against the seeded bh_workspaces
    table during the dynamic refresh test.
    """
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ('admin@test.local', 'x', 'Admin', 'admin')
            RETURNING id
            """
        )
        member_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ('alice@test.local', 'x', 'Alice', 'member')
            RETURNING id
            """
        )
        outsider_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ('bob@test.local', 'x', 'Bob', 'member')
            RETURNING id
            """
        )

        workspace_id = await conn.fetchval(
            """
            INSERT INTO public.bh_workspaces
                (name, system_prompt, permitted_schemas, created_by)
            VALUES ('Workshop', $1, $2, $3)
            RETURNING id
            """,
            _ORIGINAL_PROMPT,
            ["public"],  # SchemaGuard allows SELECTs against public.*
            admin_id,
        )

        # Membership: admin (owner) + alice (member). Bob is intentionally
        # left out so admin/member access paths are exercised cleanly.
        await conn.execute(
            """
            INSERT INTO public.bh_workspace_users (workspace_id, user_id, role)
            VALUES ($1, $2, 'owner'), ($1, $3, 'member')
            """,
            workspace_id,
            admin_id,
            member_id,
        )

        # A static pinned-context entry — refresh must reject this with 400.
        static_id = await conn.fetchval(
            """
            INSERT INTO public.bh_pinned_context
                (workspace_id, context_type, title, content, priority)
            VALUES ($1, 'static', 'House rule', 'Always cite sources.', 100)
            RETURNING id
            """,
            workspace_id,
        )

        # A dynamic pinned-context entry. The query is intentionally an
        # unqualified SELECT against a known-existing table after migrations,
        # so SchemaGuard's `permitted_schemas=['public']` plus the search_path
        # set by the refresh handler resolves bh_workspaces to public.bh_workspaces.
        dynamic_id = await conn.fetchval(
            """
            INSERT INTO public.bh_pinned_context
                (workspace_id, context_type, title, query, priority)
            VALUES ($1, 'dynamic', 'Workspace inventory', $2, 100)
            RETURNING id
            """,
            workspace_id,
            "SELECT id, name FROM bh_workspaces ORDER BY id",
        )

    return {
        "admin_id": admin_id,
        "member_id": member_id,
        "outsider_id": outsider_id,
        "workspace_id": workspace_id,
        "static_id": static_id,
        "dynamic_id": dynamic_id,
    }


@pytest_asyncio.fixture
async def workspaces_env(fresh_db, db_settings) -> AsyncIterator[dict]:
    """Bring up an isolated DB + app + seeded users/workspace/pinned-contexts.

    Yields a dict with:
      - ``client``  : ``httpx.AsyncClient`` bound to the app (in-process)
      - ``seeds``   : the user/workspace/pinned-context ids
      - ``headers`` : ``{role_key: {"Authorization": "Bearer <jwt>"}}``
      - ``pool``    : the asyncpg pool (for direct DB asserts)
    """
    config = _make_config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)

    seeds = await _seed_world(pool)

    # Mint JWTs against the same Config used by the app's auth middleware.
    from backend.services.auth import AuthService

    auth = AuthService(pool, config)
    headers = {
        "admin": {
            "Authorization": "Bearer "
            + auth.generate_access_token(
                seeds["admin_id"], "admin@test.local", "admin"
            ),
        },
        "member": {
            "Authorization": "Bearer "
            + auth.generate_access_token(
                seeds["member_id"], "alice@test.local", "member"
            ),
        },
        "outsider": {
            "Authorization": "Bearer "
            + auth.generate_access_token(
                seeds["outsider_id"], "bob@test.local", "member"
            ),
        },
    }

    app = _build_app(config)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield {
                "client": client,
                "seeds": seeds,
                "headers": headers,
                "pool": pool,
            }
        finally:
            await close_pool()


# ---------------------------------------------------------------------------
# system_prompt PATCH/GET tests (R5.6, R6.6, R6.8)
# ---------------------------------------------------------------------------


async def test_patch_oversize_system_prompt_returns_400(workspaces_env):
    """PATCH with a 60,000-char ``system_prompt`` → 400 (R6.6).

    The router enforces a 50,000-char hard cap. Anything over that must be
    rejected before a row update happens, so the original prompt should
    survive on disk.
    """
    client = workspaces_env["client"]
    seeds = workspaces_env["seeds"]
    pool = workspaces_env["pool"]

    long_prompt = "x" * 60_000
    resp = await client.patch(
        f"/api/workspaces/{seeds['workspace_id']}",
        json={"system_prompt": long_prompt},
        headers=workspaces_env["headers"]["admin"],
    )
    assert resp.status_code == 400, resp.text
    # Error mentions the limit so a UI can surface it inline.
    assert "50000" in resp.text or "50,000" in resp.text or "maximum length" in resp.text

    # DB sanity: the prompt was NOT mutated.
    async with pool.acquire() as conn:
        prompt = await conn.fetchval(
            "SELECT system_prompt FROM public.bh_workspaces WHERE id = $1",
            seeds["workspace_id"],
        )
    assert prompt == _ORIGINAL_PROMPT


async def test_patch_system_prompt_as_non_admin_returns_403(workspaces_env):
    """Non-admin sending ``system_prompt`` in PATCH body → 403 (R6.8).

    A workspace member can update other fields but must never edit the
    system prompt — that's an admin-only knob. The original prompt must
    remain unchanged.
    """
    client = workspaces_env["client"]
    seeds = workspaces_env["seeds"]
    pool = workspaces_env["pool"]

    resp = await client.patch(
        f"/api/workspaces/{seeds['workspace_id']}",
        json={"system_prompt": "I am hijacking this prompt."},
        headers=workspaces_env["headers"]["member"],
    )
    assert resp.status_code == 403, resp.text

    async with pool.acquire() as conn:
        prompt = await conn.fetchval(
            "SELECT system_prompt FROM public.bh_workspaces WHERE id = $1",
            seeds["workspace_id"],
        )
    assert prompt == _ORIGINAL_PROMPT, (
        "non-admin PATCH should not have written to system_prompt"
    )


async def test_member_get_returns_200_with_system_prompt(workspaces_env):
    """GET /api/workspaces/{id} as a workspace member → 200 with prompt (R5.6).

    Members can view the system prompt — only the edit path is admin-locked.
    """
    client = workspaces_env["client"]
    seeds = workspaces_env["seeds"]

    resp = await client.get(
        f"/api/workspaces/{seeds['workspace_id']}",
        headers=workspaces_env["headers"]["member"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == seeds["workspace_id"]
    assert body["system_prompt"] == _ORIGINAL_PROMPT


# ---------------------------------------------------------------------------
# Pinned-context refresh tests (R7.7, R7.9)
# ---------------------------------------------------------------------------


async def test_refresh_static_pinned_context_returns_400(workspaces_env):
    """POST refresh on an entry with ``context_type='static'`` → 400 (R7.7).

    Static entries are inherently un-refreshable — there's no query to
    re-execute. The route must reject the operation rather than silently
    no-op so a UI can disable the button on static rows.
    """
    client = workspaces_env["client"]
    seeds = workspaces_env["seeds"]

    resp = await client.post(
        f"/api/workspaces/{seeds['workspace_id']}"
        f"/pinned-context/{seeds['static_id']}/refresh",
        headers=workspaces_env["headers"]["admin"],
    )
    assert resp.status_code == 400, resp.text


async def test_refresh_dynamic_pinned_context_returns_200_and_updates_cache(
    workspaces_env,
):
    """POST refresh on a dynamic entry → 200 with cache+timestamp updated (R7.7).

    The query (SELECT id, name FROM bh_workspaces) must execute against
    the workspace's permitted_schemas (which includes 'public'); the
    cached_result must contain the seeded workspace name; cached_at and
    token_estimate must both be set; and the DB row must reflect the same
    values returned by the API (R7.9 — round-trip consistency).
    """
    client = workspaces_env["client"]
    seeds = workspaces_env["seeds"]
    pool = workspaces_env["pool"]

    # Pre-state: cached_result is NULL, cached_at is NULL.
    async with pool.acquire() as conn:
        before = await conn.fetchrow(
            """
            SELECT cached_result, cached_at, token_estimate
              FROM public.bh_pinned_context WHERE id = $1
            """,
            seeds["dynamic_id"],
        )
    assert before["cached_result"] is None
    assert before["cached_at"] is None

    resp = await client.post(
        f"/api/workspaces/{seeds['workspace_id']}"
        f"/pinned-context/{seeds['dynamic_id']}/refresh",
        headers=workspaces_env["headers"]["admin"],
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Response shape: cached_result + ISO8601 cached_at + non-negative token estimate.
    assert "cached_result" in body
    assert "cached_at" in body
    assert "token_estimate" in body
    assert isinstance(body["cached_result"], str)
    assert isinstance(body["cached_at"], str) and body["cached_at"]
    assert body["token_estimate"] >= 0

    # Result content reflects the workspace seeded for this test.
    assert "Workshop" in body["cached_result"], (
        f"refreshed cache should contain seeded workspace name, got: "
        f"{body['cached_result']!r}"
    )
    # Header row from the table-style render confirms the SELECT executed.
    assert "id" in body["cached_result"] and "name" in body["cached_result"]

    # DB sanity: row is in sync with what was returned to the caller.
    async with pool.acquire() as conn:
        after = await conn.fetchrow(
            """
            SELECT cached_result, cached_at, token_estimate
              FROM public.bh_pinned_context WHERE id = $1
            """,
            seeds["dynamic_id"],
        )
    assert after["cached_result"] == body["cached_result"]
    assert after["cached_at"] is not None
    assert after["token_estimate"] == body["token_estimate"]
