"""
Smoke + RBAC tests for /api/scheduled-prompts/* endpoints.

End-to-end exercises ``backend.routers.scheduled_prompts`` against a fresh
ephemeral Postgres DB (with migrations applied and admin/member users +
workspaces seeded). Uses ``httpx.AsyncClient`` with ``ASGITransport`` so
the test never touches a real network — every request is dispatched
in-process to the FastAPI app.

For ``run-now`` we attach a stub object as ``app.state.hook_engine`` whose
``_execute_hook`` method writes a ``bh_hook_log`` row directly. This lets
us exercise the router → service → engine handoff and the log-readback
path without standing up Anthropic, APScheduler, or n8n. The router only
ever calls ``_execute_hook`` and reads the resulting log row, so a stub
that mirrors that contract is enough to validate the surface.

Coverage (per task 15.2):
  - create with invalid cron → 400 with ``invalid_cron`` error code     (R11.3, R11.11)
  - create scoped to other user's private workspace → 403               (R11.3)
  - run-now triggers immediate execution and writes a bh_hook_log row   (R11.9)
  - log endpoint returns the last 10 entries newest first               (R11.10)

Validates: Requirements R11.3, R11.9, R11.10, R11.11
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.config import Config
from backend.database import close_pool, get_pool, init_pool, run_migrations


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
        JWT_SECRET="test-secret-for-scheduled-prompts-router-tests",
        N8N_BASE="http://localhost:5678",
    )


class _StubHookEngine:
    """Minimal stand-in for ``HookEngine`` for the run-now test.

    The router only calls ``_execute_hook(hook, context)`` on the engine
    pulled off ``app.state.hook_engine``. We mirror that one method and
    have it write a single ``bh_hook_log`` row with a canned snippet so
    the service's log-readback path returns a deterministic shape. No
    AI is invoked — that's the whole point of the stub.

    Each call appends the executed hook id to ``calls`` so the test can
    assert exactly one execution happened per ``run-now`` request.
    """

    def __init__(self) -> None:
        self.calls: list[int] = []

    async def _execute_hook(self, hook: dict, context: Any) -> None:
        self.calls.append(hook["id"])
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO public.bh_hook_log
                    (hook_id, event_type, trigger_data, action_result, success)
                VALUES ($1, $2, $3::jsonb, $4::jsonb, true)
                """,
                hook["id"],
                hook["event_type"],
                json.dumps({"user_id": getattr(context, "user_id", None)}),
                json.dumps({"content": "stub-response"}),
            )


def _build_app(config: Config, hook_engine: Any | None = None) -> FastAPI:
    """Construct a minimal FastAPI app that mounts only the scheduled
    prompts router.

    We avoid the project's full ``lifespan`` startup (model provider, real
    hook engine, websocket manager) — none are needed for HTTP-level
    tests of /api/scheduled-prompts/*. The DB pool is owned by the
    fixture; ``app.state.config`` is needed by the auth middleware to
    construct an ``AuthService``. ``app.state.hook_engine`` is optional —
    the router returns 503 when it's missing, which we exploit to keep
    the create/RBAC tests independent of the engine stub.
    """
    app = FastAPI()
    app.state.config = config
    if hook_engine is not None:
        app.state.hook_engine = hook_engine

    from backend.routers.scheduled_prompts import router as sp_router

    app.include_router(sp_router)
    return app


async def _seed_users_and_workspaces(pool: asyncpg.Pool) -> dict:
    """Create admin + 2 members + 2 workspaces.

    Layout:
      * admin — admin role; member of neither workspace by default
        (admins bypass the membership check via ``role == 'admin'``).
      * alice — owner of workspace ``alpha``.
      * bob   — owner of workspace ``beta``; NOT a member of ``alpha``.

    Bob trying to create a scheduled prompt scoped to ``alpha`` exercises
    the cross-workspace 403 path.
    """
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
        alice_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'member')
            RETURNING id
            """,
            "alice@test.local",
            "x",
            "Alice",
        )
        bob_id = await conn.fetchval(
            """
            INSERT INTO public.bh_users (email, password_hash, display_name, role)
            VALUES ($1, $2, $3, 'member')
            RETURNING id
            """,
            "bob@test.local",
            "x",
            "Bob",
        )

        ws_alpha = await conn.fetchval(
            """
            INSERT INTO public.bh_workspaces (name, description, system_prompt, created_by)
            VALUES ('Alpha', 'Alice''s workspace', '', $1)
            RETURNING id
            """,
            alice_id,
        )
        ws_beta = await conn.fetchval(
            """
            INSERT INTO public.bh_workspaces (name, description, system_prompt, created_by)
            VALUES ('Beta', 'Bob''s workspace', '', $1)
            RETURNING id
            """,
            bob_id,
        )

        await conn.execute(
            """
            INSERT INTO public.bh_workspace_users (workspace_id, user_id, role)
            VALUES ($1, $2, 'owner'), ($3, $4, 'owner')
            """,
            ws_alpha,
            alice_id,
            ws_beta,
            bob_id,
        )

    return {
        "admin": {"id": admin_id, "email": "admin@test.local", "role": "admin"},
        "alice": {"id": alice_id, "email": "alice@test.local", "role": "member"},
        "bob": {"id": bob_id, "email": "bob@test.local", "role": "member"},
        "ws_alpha": ws_alpha,
        "ws_beta": ws_beta,
    }


@pytest_asyncio.fixture
async def sp_env(fresh_db, db_settings) -> AsyncIterator[dict]:
    """Bring up an isolated DB + app + seeded users + auth tokens.

    Yields a dict with:
      - ``client``       : ``httpx.AsyncClient`` bound to the app (in-process)
      - ``users``        : the seeded user records (admin, alice, bob)
      - ``workspaces``   : ``{alpha, beta}`` workspace ids
      - ``headers``      : ``{role_key: {"Authorization": "Bearer <jwt>"}}``
      - ``pool``         : the asyncpg pool (for direct DB asserts)
      - ``hook_engine``  : the ``_StubHookEngine`` instance attached to
        ``app.state`` so tests can assert on ``calls``.
    """
    config = _make_config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)

    seeds = await _seed_users_and_workspaces(pool)

    # Mint JWTs against the same Config used by the app's auth middleware.
    from backend.services.auth import AuthService

    auth = AuthService(pool, config)
    headers = {
        role: {
            "Authorization": "Bearer "
            + auth.generate_access_token(seeds[role]["id"], seeds[role]["email"], seeds[role]["role"]),
        }
        for role in ("admin", "alice", "bob")
    }

    hook_engine = _StubHookEngine()
    app = _build_app(config, hook_engine=hook_engine)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        try:
            yield {
                "client": client,
                "users": {k: seeds[k] for k in ("admin", "alice", "bob")},
                "workspaces": {"alpha": seeds["ws_alpha"], "beta": seeds["ws_beta"]},
                "headers": headers,
                "pool": pool,
                "hook_engine": hook_engine,
            }
        finally:
            await close_pool()


# ---------------------------------------------------------------------------
# Helpers — payload builders
# ---------------------------------------------------------------------------


def _good_payload(workspace_id: int, **overrides) -> dict:
    """Default valid create-payload; tests override fields as needed."""
    base = {
        "name": "Weekly digest",
        "workspace_id": workspace_id,
        "prompt_template": "Summarize this week's spending.",
        "cron_expression": "0 8 * * 0",  # Sundays at 8am
        "delivery_method": "pin",
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_with_invalid_cron_returns_400(sp_env):
    """POST with an invalid cron expression → 400 + ``invalid_cron``
    error code echoing back the offending expression (R11.11).

    Routes the service-layer ``CronInvalid`` exception through the
    router's error translator. Asserts no row was persisted so the
    400 isn't masking a half-written write.
    """
    client = sp_env["client"]
    pool = sp_env["pool"]
    ws_id = sp_env["workspaces"]["alpha"]

    bad = _good_payload(ws_id, cron_expression="not a cron expression")

    resp = await client.post(
        "/api/scheduled-prompts",
        json=bad,
        headers=sp_env["headers"]["alice"],
    )
    assert resp.status_code == 400, resp.text

    detail = resp.json()["detail"]
    assert isinstance(detail, dict), f"expected structured detail, got {detail!r}"
    assert detail.get("error") == "invalid_cron"
    assert detail.get("expression") == "not a cron expression"

    # No row written.
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.bh_hooks WHERE workspace_id = $1",
            ws_id,
        )
    assert count == 0, "invalid-cron POST should not have persisted a row"


async def test_create_for_other_users_private_workspace_returns_403(sp_env):
    """Bob POSTs with workspace_id pointing at Alice's workspace → 403
    (R11.3).

    The service raises ``Forbidden`` which the router maps to 403. The
    body is otherwise valid (cron passes, fields all present), so the
    only reason for the rejection is the workspace-membership check.
    """
    client = sp_env["client"]
    pool = sp_env["pool"]
    ws_alpha = sp_env["workspaces"]["alpha"]

    payload = _good_payload(ws_alpha, name="Bob tries to write to Alpha")

    resp = await client.post(
        "/api/scheduled-prompts",
        json=payload,
        headers=sp_env["headers"]["bob"],
    )
    assert resp.status_code == 403, resp.text

    # No row leaked into Alice's workspace.
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.bh_hooks WHERE workspace_id = $1",
            ws_alpha,
        )
    assert count == 0, "cross-workspace POST should not have persisted a row"


async def test_run_now_triggers_immediate_execution_and_writes_log_row(sp_env):
    """``POST /{id}/run-now`` invokes the engine stub and the log-readback
    path returns the freshest log row with status='success' (R11.9).

    Workflow:
      1. Alice creates a scheduled prompt in her own workspace.
      2. Verify no log rows exist for the hook yet.
      3. POST run-now and assert:
         - 200 with ``status=='success'`` and a ``response_snippet``
           drawn from the stub's canned ``action_result.content``.
         - Exactly one engine ``_execute_hook`` call happened.
         - Exactly one ``bh_hook_log`` row now exists for the hook.
    """
    client = sp_env["client"]
    pool = sp_env["pool"]
    hook_engine = sp_env["hook_engine"]
    ws_id = sp_env["workspaces"]["alpha"]

    # 1) Create a scheduled prompt as Alice.
    create_resp = await client.post(
        "/api/scheduled-prompts",
        json=_good_payload(ws_id),
        headers=sp_env["headers"]["alice"],
    )
    assert create_resp.status_code == 200, create_resp.text
    hook_id = create_resp.json()["id"]
    assert isinstance(hook_id, int)

    # 2) No log rows yet.
    async with pool.acquire() as conn:
        before = await conn.fetchval(
            "SELECT COUNT(*) FROM public.bh_hook_log WHERE hook_id = $1",
            hook_id,
        )
    assert before == 0, "fresh hook should have no log rows yet"

    # 3) Run now.
    run_resp = await client.post(
        f"/api/scheduled-prompts/{hook_id}/run-now",
        headers=sp_env["headers"]["alice"],
    )
    assert run_resp.status_code == 200, run_resp.text
    body = run_resp.json()
    assert body["status"] == "success", body
    assert isinstance(body.get("run_id"), int)
    # Snippet is derived from the stub's action_result.content.
    assert body.get("response_snippet") == "stub-response"

    # Exactly one engine invocation, targeting the hook we just created.
    assert hook_engine.calls == [hook_id], (
        f"expected exactly one _execute_hook call for hook {hook_id}, "
        f"got {hook_engine.calls!r}"
    )

    # Exactly one log row was written (by the stub) and matches the run.
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, success, action_result FROM public.bh_hook_log
            WHERE hook_id = $1
            """,
            hook_id,
        )
    assert len(rows) == 1, f"expected one log row, got {[dict(r) for r in rows]!r}"
    assert rows[0]["success"] is True
    assert rows[0]["id"] == body["run_id"]


async def test_log_endpoint_returns_last_10_entries_newest_first(sp_env):
    """``GET /{id}/log`` returns the 10 newest entries, newest first
    (R11.10).

    We hand-seed 12 ``bh_hook_log`` rows with explicit ascending
    timestamps so the test fails if the route accidentally orders by
    id, returns more than the requested limit, or drops the oldest
    entries instead of the newest.
    """
    client = sp_env["client"]
    pool = sp_env["pool"]
    ws_id = sp_env["workspaces"]["alpha"]

    create_resp = await client.post(
        "/api/scheduled-prompts",
        json=_good_payload(ws_id),
        headers=sp_env["headers"]["alice"],
    )
    assert create_resp.status_code == 200, create_resp.text
    hook_id = create_resp.json()["id"]

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Insert 12 rows. ``executed_at`` is monotonically increasing with
    # ``i``, so the most recent entry is i=11 ("entry-11").
    async with pool.acquire() as conn:
        for i in range(12):
            await conn.execute(
                """
                INSERT INTO public.bh_hook_log
                    (hook_id, event_type, success, action_result, executed_at)
                VALUES ($1, 'schedule', true, $2::jsonb, $3)
                """,
                hook_id,
                json.dumps({"content": f"entry-{i}"}),
                base + timedelta(minutes=i),
            )

    # Default limit is 10.
    resp = await client.get(
        f"/api/scheduled-prompts/{hook_id}/log",
        headers=sp_env["headers"]["alice"],
    )
    assert resp.status_code == 200, resp.text
    log_rows = resp.json()

    # Exactly 10 entries — drops the two oldest.
    assert len(log_rows) == 10, f"expected 10 entries, got {len(log_rows)}: {log_rows!r}"

    # Newest first: i=11, 10, ..., 2.
    snippets = [r["response_snippet"] for r in log_rows]
    expected = [f"entry-{i}" for i in range(11, 1, -1)]
    assert snippets == expected, (
        f"log entries not in newest-first order — got {snippets!r}, expected {expected!r}"
    )

    # executed_at is itself monotonically decreasing.
    times = [r["executed_at"] for r in log_rows]
    assert times == sorted(times, reverse=True), (
        f"executed_at not in descending order: {times!r}"
    )
