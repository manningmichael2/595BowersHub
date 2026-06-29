"""Per-user notification routing — alerts now go through NotificationService
instead of the single shared-Pushover bypass.

Covers the novel orchestration in `notify_users`:
- web push is per-user; quiet-hours users are skipped
- the shared Pushover account fires AT MOST ONCE even if several recipients
  opted in (no duplicate pushes), and only for awake users
and the recipient resolvers + the continuity seed migration.
"""

from __future__ import annotations

from datetime import time as dt_time
from typing import AsyncIterator

import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import authz
from backend.services.notifications import NotificationService


pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-notif-routing",
        N8N_BASE="http://localhost:5678",
    )


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    async with pool.acquire() as conn:
        admin_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('a@t','x','A','admin') RETURNING id")
        member_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t','x','M','member') RETURNING id")
        inactive_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role, is_active) "
            "VALUES ('i@t','x','I','member', false) RETURNING id")
    try:
        yield {"pool": pool, "config": config,
               "admin_id": admin_id, "member_id": member_id, "inactive_id": inactive_id}
    finally:
        await close_pool()


async def _set_prefs(pool, user_id, *, web_push, pushover, quiet_start=None, quiet_end=None):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO public.bh_notification_prefs "
            "(user_id, event_type, web_push, pushover, quiet_start, quiet_end) "
            "VALUES ($1,'default',$2,$3,$4,$5) "
            "ON CONFLICT (user_id, event_type) DO UPDATE SET "
            "web_push=EXCLUDED.web_push, pushover=EXCLUDED.pushover, "
            "quiet_start=EXCLUDED.quiet_start, quiet_end=EXCLUDED.quiet_end",
            user_id, web_push, pushover, quiet_start, quiet_end)


def _stub_delivery(svc):
    """Replace the two delivery primitives with counting stubs so the routing
    logic is tested without network or VAPID/Pushover config."""
    calls = {"web_push": [], "pushover": 0}

    async def fake_web_push(user_id, title, message):
        calls["web_push"].append(user_id)
        return True

    async def fake_pushover(title, message, url=None, url_title=None, priority=0):
        calls["pushover"] += 1
        return True

    svc._send_web_push = fake_web_push
    svc.send_pushover = fake_pushover
    return calls


async def test_pushover_fires_once_for_many_recipients(env):
    # Two users both opted into Pushover → the shared account must fire ONCE.
    await _set_prefs(env["pool"], env["admin_id"], web_push=True, pushover=True)
    await _set_prefs(env["pool"], env["member_id"], web_push=True, pushover=True)

    svc = NotificationService(env["config"])
    calls = _stub_delivery(svc)
    result = await svc.notify_users(
        [env["admin_id"], env["member_id"]], "budget", "T", "M")

    assert calls["pushover"] == 1           # shared account, deduped
    assert sorted(calls["web_push"]) == sorted([env["admin_id"], env["member_id"]])
    assert result["web_push_count"] == 2
    assert result["pushover_sent"] is True
    assert result["attempted"] == 2
    assert result["delivered"] is True


async def test_quiet_hours_skips_user(env):
    # A 00:00–23:59 window always contains "now", so this user is suppressed.
    await _set_prefs(env["pool"], env["admin_id"], web_push=True, pushover=True,
                     quiet_start=dt_time(0, 0), quiet_end=dt_time(23, 59))
    await _set_prefs(env["pool"], env["member_id"], web_push=True, pushover=False)

    svc = NotificationService(env["config"])
    calls = _stub_delivery(svc)
    result = await svc.notify_users(
        [env["admin_id"], env["member_id"]], "reminder", "T", "M")

    # admin is in quiet hours → skipped entirely; only member processed.
    assert calls["web_push"] == [env["member_id"]]
    assert calls["pushover"] == 0           # member has pushover off
    assert result["attempted"] == 1


async def test_duplicate_recipient_ids_are_deduped(env):
    await _set_prefs(env["pool"], env["member_id"], web_push=True, pushover=False)
    svc = NotificationService(env["config"])
    calls = _stub_delivery(svc)
    result = await svc.notify_users(
        [env["member_id"], env["member_id"]], "gameday", "T", "M")
    assert calls["web_push"] == [env["member_id"]]   # not twice
    assert result["attempted"] == 1


async def test_recipient_resolvers(env):
    from backend.services.alerts import _all_active_user_ids, _finance_user_ids
    async with env["pool"].acquire() as conn:
        active = await _all_active_user_ids(conn)
        finance = await _finance_user_ids(conn)
    # Inactive user excluded from both; active admin+member included.
    assert env["inactive_id"] not in active
    assert set(active) == {env["admin_id"], env["member_id"]}
    # Both active roles resolve finance.read by default.
    assert set(finance) == {env["admin_id"], env["member_id"]}


async def test_seed_sql_pushover_on_and_preserves_existing(env):
    """The 0046 seed statement gives active users a pushover-on default row, and
    is idempotent — it never clobbers a pref the user already set."""
    seed = (
        "INSERT INTO public.bh_notification_prefs (user_id, event_type, web_push, pushover) "
        "SELECT id, 'default', true, true FROM public.bh_users WHERE is_active = true "
        "ON CONFLICT (user_id, event_type) DO NOTHING"
    )
    # Member opted OUT before the seed runs; admin has no row yet.
    await _set_prefs(env["pool"], env["member_id"], web_push=True, pushover=False)

    async with env["pool"].acquire() as conn:
        await conn.execute(seed)
        admin_po = await conn.fetchval(
            "SELECT pushover FROM public.bh_notification_prefs "
            "WHERE user_id=$1 AND event_type='default'", env["admin_id"])
        member_po = await conn.fetchval(
            "SELECT pushover FROM public.bh_notification_prefs "
            "WHERE user_id=$1 AND event_type='default'", env["member_id"])
        # Inactive user is not seeded.
        inactive_row = await conn.fetchval(
            "SELECT count(*) FROM public.bh_notification_prefs "
            "WHERE user_id=$1", env["inactive_id"])

    assert admin_po is True            # newly seeded → pushover on
    assert member_po is False          # ON CONFLICT DO NOTHING preserved opt-out
    assert inactive_row == 0           # inactive users excluded
