"""
Tests for the briefing router (`backend.routers.briefing`).

End-to-end exercises the briefing endpoints against a fresh ephemeral
Postgres database with all migrations applied and a hand-seeded set of
users + workspaces + briefing messages. Auth is replaced with a
``dependency_overrides`` shim so we can pivot the "current user" per-test
without minting real JWTs.

Covered (per task 16.2):
  - GET /api/briefing/latest with no briefing in the last 24h returns
    ``{"briefing_id": null}`` (R8.3) — exercised both with no briefing
    at all and with a 25h-old briefing.
  - GET /api/briefing/latest with a fresh briefing (1h old) returns the
    parsed sections.
  - Briefing markdown that omits Weather still returns a section for
    Weather, with content equal to the ``"—"`` placeholder (R8.7).
  - A user who is a member of a non-target workspace gets 403 when they
    request a briefing for a workspace they're not assigned to (R8.1
    workspace access control).
  - POST /api/briefing/generate-now is reachable and returns 503 when
    the model provider isn't available on app.state. We don't hit
    Anthropic in tests; the 503 path on missing app state is enough to
    confirm the route wiring + fail-shut behavior.

Validates: Requirements R8.1, R8.3, R8.7
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

import asyncpg
import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _apply_migrations(db_name: str, db_settings: dict) -> tuple[Config, asyncpg.Pool]:
    """Initialize the project pool against ``db_name`` and run all migrations."""
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    await run_migrations(pool)
    return config, pool


async def _seed_world(pool: asyncpg.Pool) -> dict[str, Any]:
    """Seed two users + two workspaces + memberships so the access checks have
    something real to operate on.

    Layout:
      * alice — member of workspace ``target`` (her "morning card" workspace)
      * bob   — member of workspace ``other`` (NOT a member of ``target``)

    The 403 test uses bob → ``target`` to confirm a non-member is rejected.
    """
    async with pool.acquire() as conn:
        alice_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ('alice@test.local', 'x', 'Alice', 'member')
            RETURNING id
            """
        )
        bob_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ('bob@test.local', 'x', 'Bob', 'member')
            RETURNING id
            """
        )

        ws_target = await conn.fetchval(
            """
            INSERT INTO public.bh_workspaces (name, description, system_prompt, created_by)
            VALUES ('Target', 'Alice''s morning-card workspace', '', $1)
            RETURNING id
            """,
            alice_id,
        )
        ws_other = await conn.fetchval(
            """
            INSERT INTO public.bh_workspaces (name, description, system_prompt, created_by)
            VALUES ('Other', 'Bob''s workspace', '', $1)
            RETURNING id
            """,
            bob_id,
        )

        await conn.execute(
            """
            INSERT INTO public.bh_workspace_users (workspace_id, user_id, role)
            VALUES ($1, $2, 'owner'), ($3, $4, 'owner')
            """,
            ws_target,
            alice_id,
            ws_other,
            bob_id,
        )

    return {
        "alice_id": alice_id,
        "bob_id": bob_id,
        "ws_target": ws_target,
        "ws_other": ws_other,
    }


async def _insert_briefing_message(
    pool: asyncpg.Pool,
    *,
    workspace_id: int,
    user_id: int,
    content: str,
    created_at: datetime,
) -> int:
    """Insert a "Daily Briefing" conversation + system message with the
    canonical metadata shape the router scans for, at an explicit
    ``created_at``. Returns the message id.

    The router accepts either ``metadata.briefing = true`` or
    ``metadata.type = 'briefing'`` — we set both to mirror what
    ``BriefingService.deliver`` writes in the real code path.
    """
    async with pool.acquire() as conn:
        conv_id = await conn.fetchval(
            """
            INSERT INTO public.bh_conversations (workspace_id, user_id, title, created_at, updated_at)
            VALUES ($1, $2, 'Daily Briefing', $3, $3)
            RETURNING id
            """,
            workspace_id,
            user_id,
            created_at,
        )
        msg_id = await conn.fetchval(
            """
            INSERT INTO public.bh_messages
                (conversation_id, role, content, routing_layer, metadata, created_at)
            VALUES ($1, 'system', $2, 'L1', $3::jsonb, $4)
            RETURNING id
            """,
            conv_id,
            content,
            json.dumps({"briefing": True, "type": "briefing"}),
            created_at,
        )
        return int(msg_id)


@pytest_asyncio.fixture
async def briefing_app(fresh_db, db_settings):
    """Bring up an isolated FastAPI app wired to the fresh DB.

    Includes only the briefing router (and its transitive workspaces
    helper). Auth is intentionally NOT wired up here — tests install
    a ``dependency_overrides`` shim for ``get_current_user`` to pivot
    the active user.

    Yields ``(app, pool, seeds, config)`` where ``seeds`` is the dict
    produced by :func:`_seed_world`.
    """
    config, pool = await _apply_migrations(fresh_db, db_settings)
    try:
        seeds = await _seed_world(pool)

        # Local imports so module-level side effects don't load before the
        # DB pool is up.
        from backend.routers.briefing import router as briefing_router

        app = FastAPI()
        app.include_router(briefing_router)
        # The route stores config on app.state; generate-now also requires
        # ``model_provider`` — the 503 test relies on that being absent.
        app.state.config = config

        yield app, pool, seeds, config
    finally:
        await close_pool()


def _as_user(app: FastAPI, user_dict: dict) -> None:
    """Override ``get_current_user`` to return ``user_dict`` for the next request."""
    from backend.middleware.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user_dict


def _alice(seeds: dict) -> dict:
    """Build a user dict matching what ``AuthService.get_user_by_id`` returns."""
    return {
        "id": seeds["alice_id"],
        "email": "alice@test.local",
        "display_name": "Alice",
        "role": "member",
        "is_active": True,
        "settings_json": {},
    }


def _bob(seeds: dict) -> dict:
    return {
        "id": seeds["bob_id"],
        "email": "bob@test.local",
        "display_name": "Bob",
        "role": "member",
        "is_active": True,
        "settings_json": {},
    }


# ---------------------------------------------------------------------------
# GET /api/briefing/latest
# ---------------------------------------------------------------------------


async def test_no_briefing_at_all_returns_briefing_id_null(briefing_app):
    """No system briefing message exists → ``{"briefing_id": null}`` (R8.3)."""
    app, _pool, seeds, _config = briefing_app
    _as_user(app, _alice(seeds))

    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/briefing/latest?workspace_id={seeds['ws_target']}"
        )

    assert resp.status_code == 200
    assert resp.json() == {"briefing_id": None}


async def test_stale_briefing_25h_old_returns_briefing_id_null(briefing_app):
    """A briefing from 25 hours ago is treated as absent (R8.1 freshness window).

    The route only renders a briefing within the last 24 hours; older
    rows fall through to the "no briefing" response so the frontend
    can show the regenerate button instead of stale content.
    """
    app, pool, seeds, _config = briefing_app

    stale_ts = datetime.now(timezone.utc) - timedelta(hours=25)
    await _insert_briefing_message(
        pool,
        workspace_id=seeds["ws_target"],
        user_id=seeds["alice_id"],
        content="**Weather:**\nClear 60°F\n\n**Inbox:**\n3 files\n",
        created_at=stale_ts,
    )

    _as_user(app, _alice(seeds))
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/briefing/latest?workspace_id={seeds['ws_target']}"
        )

    assert resp.status_code == 200
    assert resp.json() == {"briefing_id": None}


async def test_fresh_briefing_returns_parsed_sections_with_dash_for_missing_weather(
    briefing_app,
):
    """A 1-hour-old briefing with sections except Weather returns parsed
    sections, and the omitted Weather section is rendered as the ``"—"``
    placeholder (R8.7). The other present sections come through with
    their real content.
    """
    app, pool, seeds, _config = briefing_app

    fresh_ts = datetime.now(timezone.utc) - timedelta(hours=1)
    # Briefing markdown that intentionally omits the **Weather:** section
    # to verify the parser substitutes the placeholder.
    content = (
        "Good morning!\n\n"
        "**Yesterday's Spending:**\n$10.00 across 1 transaction\n\n"
        "**Inbox:**\n0 files\n\n"
        "**Today's Schedule:**\nFree day\n\n"
        "**Anything Else:**\nNothing notable.\n"
    )
    msg_id = await _insert_briefing_message(
        pool,
        workspace_id=seeds["ws_target"],
        user_id=seeds["alice_id"],
        content=content,
        created_at=fresh_ts,
    )

    _as_user(app, _alice(seeds))
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/briefing/latest?workspace_id={seeds['ws_target']}"
        )

    assert resp.status_code == 200
    body = resp.json()

    # Top-level shape
    assert body["briefing_id"] == msg_id
    assert body["content"] == content
    assert isinstance(body["generated_at"], str) and body["generated_at"]
    assert isinstance(body["age_hours"], (int, float))
    # 1-hour-old briefing: age must be < 24h, otherwise the route would
    # have returned ``briefing_id: null`` instead of this payload.
    assert 0.0 <= body["age_hours"] < 24.0

    # Parsed sections — six canonical sections always present, in order.
    sections = body["parsed_sections"]
    assert isinstance(sections, list) and len(sections) == 6
    assert [s["key"] for s in sections] == [
        "weather",
        "yesterday_spending",
        "inbox",
        "schedule",
        "anything_else",
        "finance_insights",
    ]
    by_key = {s["key"]: s for s in sections}

    # Weather + Finance Insights omitted in the briefing → "—" placeholder (R8.7).
    assert by_key["weather"]["content"] == "—"
    assert by_key["weather"]["label"] == "Weather"
    assert by_key["finance_insights"]["content"] == "—"
    assert by_key["finance_insights"]["label"] == "Finance Insights"

    # The four sections that WERE in the markdown come through with content.
    assert by_key["yesterday_spending"]["content"] == "$10.00 across 1 transaction"
    assert by_key["inbox"]["content"] == "0 files"
    assert by_key["schedule"]["content"] == "Free day"
    assert by_key["anything_else"]["content"] == "Nothing notable."


async def test_non_member_workspace_returns_403(briefing_app):
    """Bob is a member of ``ws_other`` but NOT ``ws_target``. Requesting a
    briefing for ``ws_target`` must return 403 — workspace membership is
    enforced through ``_check_workspace_access`` (R8.1).
    """
    app, pool, seeds, _config = briefing_app

    # Seed a fresh briefing in ws_target so the 403 isn't masked by an
    # earlier "no briefing" return path.
    await _insert_briefing_message(
        pool,
        workspace_id=seeds["ws_target"],
        user_id=seeds["alice_id"],
        content="**Weather:**\nClear 60°F\n",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )

    _as_user(app, _bob(seeds))
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(
            f"/api/briefing/latest?workspace_id={seeds['ws_target']}"
        )

    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# POST /api/briefing/generate-now
# ---------------------------------------------------------------------------


async def test_generate_now_returns_503_when_model_provider_unavailable(briefing_app):
    """``POST /generate-now`` is reachable and returns 503 when
    ``app.state.model_provider`` is missing.

    Per task 16.2 we don't exercise the full Anthropic call path; instead
    we confirm the wiring is intact and the route fails shut with 503
    when the model provider isn't available — this is exactly the path
    the ``except AttributeError`` branch in the router was written to
    handle.
    """
    app, _pool, seeds, _config = briefing_app

    # The fixture deliberately doesn't set app.state.model_provider; the
    # route's AttributeError-guarded read of it should yield 503.
    assert not hasattr(app.state, "model_provider")

    _as_user(app, _alice(seeds))
    async with httpx.AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            f"/api/briefing/generate-now?workspace_id={seeds['ws_target']}"
        )

    assert resp.status_code == 503
