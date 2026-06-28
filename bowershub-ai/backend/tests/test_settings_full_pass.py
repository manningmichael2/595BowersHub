"""Settings full-pass — the sections wired up in this pass:

- Notifications: GET/PUT /api/me/notifications over the bh_notification_prefs
  `default` row, plus channel availability from server config, plus the
  NotificationService fallback to the default row for arbitrary event types.
- Profile: PATCH /api/auth/me (display name) + POST /api/auth/change-password
  (current-password check, policy, refresh-token revocation).
- Context capture opt-out: settings_json.context_capture_disabled short-circuits
  the hook-engine capture action.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations
from backend.services import authz
from backend.services.auth import AuthService
from backend.services.notifications import NotificationService


pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict, **extra) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-settings-full-pass",
        N8N_BASE="http://localhost:5678",
        **extra,
    )


def _build_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.me import router as me
    from backend.routers.auth import router as auth
    for r in (me, auth):
        app.include_router(r)
    return app


@pytest_asyncio.fixture
async def env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    auth = AuthService(pool, config)
    # A real bcrypt hash so change-password can verify the current password.
    pw_hash = AuthService.hash_password("orig-password-123")
    async with pool.acquire() as conn:
        member_id = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('m@t',$1,'M','member') RETURNING id", pw_hash)
    headers = {
        "member": {"Authorization": "Bearer " + auth.generate_access_token(member_id, "m@t", "member")},
    }
    app = _build_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "headers": headers,
                   "member_id": member_id, "config": config,
                   "fresh_db": fresh_db, "db_settings": db_settings}
        finally:
            await close_pool()


def _webpush_client(env) -> AsyncClient:
    """A client whose app has web push configured (VAPID keys set), sharing the
    same DB pool + JWT secret as the fixture so the member token still validates."""
    config = _config(
        env["fresh_db"], env["db_settings"],
        VAPID_PUBLIC_KEY="test-vapid-public", VAPID_PRIVATE_KEY="test-vapid-private",
    )
    app = _build_app(config)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ---- Notifications --------------------------------------------------------

async def test_notifications_defaults_and_availability(env):
    r = await env["client"].get("/api/me/notifications", headers=env["headers"]["member"])
    assert r.status_code == 200
    body = r.json()
    assert body["prefs"] == {
        "web_push": True, "pushover": False, "quiet_start": None, "quiet_end": None,
    }
    # No VAPID / Pushover config in the test Config → both channels unavailable.
    assert body["available"] == {"web_push": False, "pushover": False}


async def test_notifications_put_roundtrip(env):
    put = await env["client"].put(
        "/api/me/notifications",
        json={"web_push": False, "pushover": True,
              "quiet_start": "22:00", "quiet_end": "07:00"},
        headers=env["headers"]["member"],
    )
    assert put.status_code == 200
    got = (await env["client"].get("/api/me/notifications", headers=env["headers"]["member"])).json()
    assert got["prefs"] == {
        "web_push": False, "pushover": True, "quiet_start": "22:00", "quiet_end": "07:00",
    }


async def test_notifications_rejects_bad_time(env):
    r = await env["client"].put(
        "/api/me/notifications",
        json={"web_push": True, "pushover": False, "quiet_start": "25:99", "quiet_end": None},
        headers=env["headers"]["member"],
    )
    assert r.status_code == 422


async def test_notification_service_falls_back_to_default_row(env):
    # Persist the user's global (default) prefs with pushover on.
    await env["client"].put(
        "/api/me/notifications",
        json={"web_push": False, "pushover": True, "quiet_start": None, "quiet_end": None},
        headers=env["headers"]["member"],
    )
    svc = NotificationService(env["config"])
    # An arbitrary event type with no specific row should inherit the default row.
    prefs = await svc._get_preferences(env["member_id"], "budget_alert")
    assert prefs["web_push"] is False
    assert prefs["pushover"] is True


# ---- Web push subscriptions -----------------------------------------------

_SUB = {
    "endpoint": "https://push.example.com/abc123",
    "expirationTime": None,
    "keys": {"p256dh": "key-p256dh", "auth": "key-auth"},
}


async def test_push_key_unconfigured(env):
    r = await env["client"].get("/api/me/push/key", headers=env["headers"]["member"])
    assert r.status_code == 200
    assert r.json() == {"enabled": False, "public_key": None}


async def test_push_subscribe_503_when_unconfigured(env):
    r = await env["client"].post(
        "/api/me/push/subscribe", json=_SUB, headers=env["headers"]["member"])
    assert r.status_code == 503


async def test_push_subscribe_dedupes_then_unsubscribe(env):
    async with _webpush_client(env) as client:
        h = env["headers"]["member"]
        # Key is now exposed.
        key = await client.get("/api/me/push/key", headers=h)
        assert key.json() == {"enabled": True, "public_key": "test-vapid-public"}

        # Subscribe twice with the same endpoint → exactly one row (dedupe).
        assert (await client.post("/api/me/push/subscribe", json=_SUB, headers=h)).status_code == 200
        assert (await client.post("/api/me/push/subscribe", json=_SUB, headers=h)).status_code == 200
        async with env["pool"].acquire() as conn:
            n = await conn.fetchval(
                "SELECT count(*) FROM public.bh_push_subscriptions WHERE user_id=$1",
                env["member_id"])
        assert n == 1

        # Unsubscribe removes it.
        assert (await client.post(
            "/api/me/push/unsubscribe", json={"endpoint": _SUB["endpoint"]},
            headers=h)).status_code == 200
        async with env["pool"].acquire() as conn:
            n = await conn.fetchval(
                "SELECT count(*) FROM public.bh_push_subscriptions WHERE user_id=$1",
                env["member_id"])
        assert n == 0


# ---- Profile: display name ------------------------------------------------

async def test_update_display_name(env):
    r = await env["client"].patch(
        "/api/auth/me", json={"display_name": "Renamed"}, headers=env["headers"]["member"])
    assert r.status_code == 200
    assert r.json()["display_name"] == "Renamed"
    async with env["pool"].acquire() as conn:
        name = await conn.fetchval(
            "SELECT display_name FROM public.bh_users WHERE id=$1", env["member_id"])
    assert name == "Renamed"


async def test_update_display_name_rejects_blank(env):
    r = await env["client"].patch(
        "/api/auth/me", json={"display_name": "   "}, headers=env["headers"]["member"])
    assert r.status_code == 400


# ---- Profile: change password ---------------------------------------------

async def test_change_password_happy_path(env):
    r = await env["client"].post(
        "/api/auth/change-password",
        json={"current_password": "orig-password-123", "new_password": "brand-new-pass-99"},
        headers=env["headers"]["member"],
    )
    assert r.status_code == 200
    # The new hash verifies; the old one no longer does.
    async with env["pool"].acquire() as conn:
        h = await conn.fetchval(
            "SELECT password_hash FROM public.bh_users WHERE id=$1", env["member_id"])
    assert AuthService.verify_password("brand-new-pass-99", h)
    assert not AuthService.verify_password("orig-password-123", h)


async def test_change_password_wrong_current(env):
    r = await env["client"].post(
        "/api/auth/change-password",
        json={"current_password": "wrong", "new_password": "brand-new-pass-99"},
        headers=env["headers"]["member"],
    )
    assert r.status_code == 400


async def test_change_password_enforces_policy(env):
    r = await env["client"].post(
        "/api/auth/change-password",
        json={"current_password": "orig-password-123", "new_password": "short"},
        headers=env["headers"]["member"],
    )
    assert r.status_code == 400


# ---- Context capture opt-out ----------------------------------------------

async def test_context_capture_opt_out_skips(env):
    """With the opt-out set, the hook-engine capture action short-circuits before
    invoking the model."""
    from backend.services.hook_engine import HookEngine, HookEventContext

    async with env["pool"].acquire() as conn:
        await conn.execute(
            "UPDATE public.bh_users SET settings_json = '{\"context_capture_disabled\": true}'::jsonb "
            "WHERE id=$1", env["member_id"])

    # A minimal HookEngine; we only exercise _action_capture_context, which reads
    # the DB and returns before touching the model when opted out.
    engine = HookEngine.__new__(HookEngine)
    engine.model_provider = None  # never used on the opt-out path
    engine.config = env["config"]

    ctx = HookEventContext(
        user_message="I prefer dark mode.",
        assistant_message="Noted.",
        workspace_id=None,
        user_id=env["member_id"],
    )
    result = await engine._action_capture_context(ctx)
    assert result.get("skipped") is True
    assert "opted out" in result.get("reason", "").lower()
