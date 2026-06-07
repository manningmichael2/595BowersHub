"""
Unit tests for the scheduled_prompts CRUD service.

End-to-end exercises ``backend.services.scheduled_prompts`` (the thin CRUD
facade over ``bh_hooks`` rows where ``event_type='schedule'`` and
``action_type='call_ai'``) against a fresh ephemeral Postgres database
with migrations applied and a hand-seeded set of users, workspaces, and
workspace memberships.

Coverage (per task 8.2):
  - create with valid cron → returns serialized scheduled-prompt shape
    and persists a ``bh_hooks`` row
  - create with invalid cron → raises ``CronInvalid`` (the 400-shape error
    that ``backend.routers.scheduled_prompts`` translates to HTTP 400)
  - update toggles ``is_enabled`` (both via ``update`` and ``toggle``)
  - list filters to the user's accessible workspaces (no leakage of rows
    belonging to workspaces the user is not a member of)
  - get_log returns rows in reverse-chronological order

Validates: Requirements R11.1, R11.7, R11.10, R11.11
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import asyncpg
import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures: bring up a real ephemeral DB, apply migrations, seed users +
# workspaces + workspace_users so the service-layer access checks have
# something real to operate on.
# ---------------------------------------------------------------------------


async def _apply_migrations(db_name: str, db_settings: dict) -> asyncpg.Pool:
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
    return pool


async def _seed_users_and_workspaces(pool: asyncpg.Pool) -> dict:
    """Create two member users and two workspaces; user_a has access to
    workspace_a, user_b has access to workspace_b. Returns a dict of
    seeded ids the tests can refer to.
    """
    async with pool.acquire() as conn:
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

        ws_a_id = await conn.fetchval(
            """
            INSERT INTO public.bh_workspaces (name, description, system_prompt, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "Alpha",
            "Alice's workspace",
            "",
            user_a_id,
        )
        ws_b_id = await conn.fetchval(
            """
            INSERT INTO public.bh_workspaces (name, description, system_prompt, created_by)
            VALUES ($1, $2, $3, $4)
            RETURNING id
            """,
            "Beta",
            "Bob's workspace",
            "",
            user_b_id,
        )

        await conn.execute(
            """
            INSERT INTO public.bh_workspace_users (workspace_id, user_id, role)
            VALUES ($1, $2, 'owner'), ($3, $4, 'owner')
            """,
            ws_a_id,
            user_a_id,
            ws_b_id,
            user_b_id,
        )

    return {
        "user_a": {"id": user_a_id, "role": "member"},
        "user_b": {"id": user_b_id, "role": "member"},
        "ws_a": ws_a_id,
        "ws_b": ws_b_id,
    }


@pytest_asyncio.fixture
async def seeded_db(fresh_db, db_settings):
    """Apply migrations to a fresh DB and seed two users + two workspaces.

    Yields ``(pool, ids)`` where ``ids`` is the dict produced by
    :func:`_seed_users_and_workspaces`. Closes the pool on teardown so
    the fresh-db fixture can DROP the database cleanly.
    """
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        ids = await _seed_users_and_workspaces(pool)
        yield pool, ids
    finally:
        await close_pool()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _payload(workspace_id: int, **overrides) -> dict:
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


async def test_create_with_valid_cron_persists_hook_and_returns_scheduled_prompt_shape(
    seeded_db,
):
    """``create`` with a valid cron expression inserts a ``bh_hooks`` row and
    returns the public scheduled-prompt shape.

    Validates: R11.1 (the row is shaped as a scheduled-prompt: schedule +
    call_ai + cron + workspace), R11.11 (cron validated up front).
    """
    from backend.services import scheduled_prompts as svc

    pool, ids = seeded_db
    user = ids["user_a"]
    ws_id = ids["ws_a"]

    result = await svc.create(user, _payload(ws_id))

    # Public shape — checked field-by-field rather than equality so we
    # don't break when cosmetic fields like ``cron_human`` change.
    assert isinstance(result["id"], int)
    assert result["name"] == "Weekly digest"
    assert result["workspace_id"] == ws_id
    assert result["prompt_template"] == "Summarize this week's spending."
    assert result["cron_expression"] == "0 8 * * 0"
    assert result["delivery_method"] == "pin"
    assert result["is_enabled"] is True
    assert result["last_run"] is None
    assert result["last_status"] is None
    # cron_human is cosmetic but must be a non-empty string when cron is set
    assert isinstance(result["cron_human"], str) and result["cron_human"]

    # Underlying row exists with the expected event/action shape.
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM public.bh_hooks WHERE id = $1",
            result["id"],
        )
    assert row is not None
    assert row["event_type"] == "schedule"
    assert row["action_type"] == "call_ai"
    assert row["cron_expression"] == "0 8 * * 0"
    assert row["is_enabled"] is True
    assert row["workspace_id"] == ws_id

    cfg = row["action_config"]
    if isinstance(cfg, str):
        cfg = json.loads(cfg)
    assert cfg["prompt"] == "Summarize this week's spending."
    assert cfg["delivery_method"] == "pin"
    assert cfg["workspace_id"] == ws_id
    assert "model" in cfg  # default model gets stamped in by the service


async def test_create_with_invalid_cron_raises_cron_invalid(seeded_db):
    """``create`` with an invalid cron expression raises ``CronInvalid``.

    The router layer translates this to HTTP 400; verifying the service
    raises the right exception type is the unit-level equivalent of the
    ``"400-shape error"`` requirement in the task description.

    Validates: R11.11 (invalid cron rejected with descriptive error).
    """
    from backend.services import scheduled_prompts as svc

    pool, ids = seeded_db
    user = ids["user_a"]
    ws_id = ids["ws_a"]

    bad_payload = _payload(ws_id, cron_expression="not a cron expression")

    with pytest.raises(svc.CronInvalid) as exc:
        await svc.create(user, bad_payload)
    # Error carries the offending expression so the router can produce a
    # descriptive 400 message (R11.11).
    assert exc.value.expr == "not a cron expression"

    # Nothing was persisted.
    async with pool.acquire() as conn:
        row_count = await conn.fetchval(
            "SELECT COUNT(*) FROM public.bh_hooks WHERE workspace_id = $1",
            ws_id,
        )
    assert row_count == 0


async def test_update_toggles_is_enabled_via_update_and_toggle(seeded_db):
    """``update`` and ``toggle`` both flip ``is_enabled`` on the underlying row.

    Validates: R11.7 (update modifies fields), R11.8 (disable sets
    is_enabled=false). The service exposes both ``update`` (general
    PATCH) and ``toggle`` (dedicated enable/disable); both must reach
    the same row state.
    """
    from backend.services import scheduled_prompts as svc

    pool, ids = seeded_db
    user = ids["user_a"]
    ws_id = ids["ws_a"]

    created = await svc.create(user, _payload(ws_id))
    hook_id = created["id"]
    assert created["is_enabled"] is True

    # 1) update({"is_enabled": False}) flips the row.
    updated = await svc.update(user, hook_id, {"is_enabled": False})
    assert updated["is_enabled"] is False
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT is_enabled FROM public.bh_hooks WHERE id = $1",
                hook_id,
            )
            is False
        )

    # 2) toggle(True) flips it back.
    toggled_on = await svc.toggle(user, hook_id, True)
    assert toggled_on["is_enabled"] is True
    async with pool.acquire() as conn:
        assert (
            await conn.fetchval(
                "SELECT is_enabled FROM public.bh_hooks WHERE id = $1",
                hook_id,
            )
            is True
        )

    # 3) toggle(False) flips it off again.
    toggled_off = await svc.toggle(user, hook_id, False)
    assert toggled_off["is_enabled"] is False


async def test_list_filters_to_users_accessible_workspaces(seeded_db):
    """``list_for_user`` returns only rows the caller can reach.

    Alice owns workspace Alpha and Bob owns workspace Beta. We seed one
    scheduled prompt per workspace, then verify Alice sees only her own
    and Bob sees only his own.

    Validates: R11.1 (list scoped to workspaces the user has access to).
    """
    from backend.services import scheduled_prompts as svc

    pool, ids = seeded_db
    user_a = ids["user_a"]
    user_b = ids["user_b"]

    # Seed one prompt per workspace, owned via each user's hook.
    a_prompt = await svc.create(
        user_a,
        _payload(ids["ws_a"], name="Alpha digest"),
    )
    b_prompt = await svc.create(
        user_b,
        _payload(ids["ws_b"], name="Beta digest"),
    )

    a_view = await svc.list_for_user(user_a)
    b_view = await svc.list_for_user(user_b)

    a_ids = {p["id"] for p in a_view}
    b_ids = {p["id"] for p in b_view}

    assert a_prompt["id"] in a_ids
    assert b_prompt["id"] not in a_ids, (
        "Alice's list leaked Bob's scheduled prompt — workspace scoping broken"
    )

    assert b_prompt["id"] in b_ids
    assert a_prompt["id"] not in b_ids, (
        "Bob's list leaked Alice's scheduled prompt — workspace scoping broken"
    )

    # And every entry returned is in fact a workspace the user has access to.
    for p in a_view:
        assert p["workspace_id"] == ids["ws_a"]
    for p in b_view:
        assert p["workspace_id"] == ids["ws_b"]


async def test_get_log_returns_rows_in_reverse_chronological_order(seeded_db):
    """``get_log`` returns the most-recent log entries first.

    We hand-seed three ``bh_hook_log`` rows with explicit, non-monotonic
    timestamps so the test fails if the service forgets the ``ORDER BY
    executed_at DESC`` clause and accidentally orders by id.

    Validates: R11.10 (last 10 execution log entries).
    """
    from backend.services import scheduled_prompts as svc

    pool, ids = seeded_db
    user = ids["user_a"]
    ws_id = ids["ws_a"]

    created = await svc.create(user, _payload(ws_id))
    hook_id = created["id"]

    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Insert three log rows whose insertion order does NOT match their
    # executed_at order. If get_log accidentally orders by id we'll see
    # ['oldest', 'newest', 'middle'] — the assert below pins the
    # executed_at order.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.bh_hook_log
                (hook_id, event_type, success, action_result, executed_at)
            VALUES ($1, 'schedule', true, $2::jsonb, $3)
            """,
            hook_id,
            json.dumps({"content": "oldest"}),
            base,  # earliest
        )
        await conn.execute(
            """
            INSERT INTO public.bh_hook_log
                (hook_id, event_type, success, action_result, executed_at)
            VALUES ($1, 'schedule', true, $2::jsonb, $3)
            """,
            hook_id,
            json.dumps({"content": "newest"}),
            base + timedelta(hours=2),  # latest
        )
        await conn.execute(
            """
            INSERT INTO public.bh_hook_log
                (hook_id, event_type, success, action_result, executed_at)
            VALUES ($1, 'schedule', true, $2::jsonb, $3)
            """,
            hook_id,
            json.dumps({"content": "middle"}),
            base + timedelta(hours=1),
        )

    log_rows = await svc.get_log(user, hook_id, limit=10)

    # Three rows, newest first.
    assert len(log_rows) == 3
    snippets = [r["response_snippet"] for r in log_rows]
    assert snippets == ["newest", "middle", "oldest"], (
        f"get_log did not return reverse-chronological order: {snippets}"
    )

    # executed_at field is itself monotonically decreasing.
    times = [r["executed_at"] for r in log_rows]
    assert times == sorted(times, reverse=True), (
        f"executed_at not in descending order: {times}"
    )


async def test_get_log_clamps_limit_and_respects_workspace_access(seeded_db):
    """``get_log`` clamps the ``limit`` argument to [1, 100] and refuses
    to return rows for a hook the caller cannot reach.

    The clamp protects against a router-layer mistake passing a giant
    limit straight through; the access check is the same workspace-
    scoping rule exercised in ``test_list_filters...``. Together they
    cover the core safety properties of get_log.
    """
    from backend.services import scheduled_prompts as svc

    pool, ids = seeded_db
    user_a = ids["user_a"]
    user_b = ids["user_b"]

    created = await svc.create(user_a, _payload(ids["ws_a"]))
    hook_id = created["id"]

    # Seed a single log row so we can test clamping with limit=0.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.bh_hook_log
                (hook_id, event_type, success, action_result, executed_at)
            VALUES ($1, 'schedule', true, $2::jsonb, now())
            """,
            hook_id,
            json.dumps({"content": "only-row"}),
        )

    # limit=0 → clamped to 1 → still returns the one row.
    rows = await svc.get_log(user_a, hook_id, limit=0)
    assert len(rows) == 1

    # Bob tries to read Alice's hook log → Forbidden.
    with pytest.raises(svc.Forbidden):
        await svc.get_log(user_b, hook_id, limit=10)
