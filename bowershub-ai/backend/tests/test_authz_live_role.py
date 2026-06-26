"""Task 4 — live-role enforcement (R1.6 / R1.7).

T-DEMOTE-1 (HTTP): a user demoted in the DB is denied on the NEXT request despite
  an unexpired JWT — get_current_user authorizes on the live bh_users row.
T-WS-1 (WebSocket): a user deactivated while a socket is open is rejected on the
  NEXT message (no reconnect); the skill gate reflects a live role change, so a
  viewer is denied a member-gated skill and a demoted member loses access.
"""

from __future__ import annotations

from typing import AsyncIterator

import asyncpg
import pytest
import pytest_asyncio
from fastapi import FastAPI, WebSocketDisconnect
from httpx import ASGITransport, AsyncClient

from backend.config import Config
from backend.database import close_pool, get_pool, init_pool, run_migrations
from backend.services import authz
from backend.services.auth import AuthService
from backend.services.skill_executor import SkillExecutor
from backend.websocket.handlers import websocket_chat_handler
from backend.websocket.manager import WebSocketManager


pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-at-least-32-bytes-long!!",
        N8N_BASE="http://localhost:5678",
    )


# === T-DEMOTE-1: HTTP live-role ============================================
def _build_db_app(config: Config) -> FastAPI:
    app = FastAPI()
    app.state.config = config
    from backend.routers.db_browser import router as db_browser_router
    app.include_router(db_browser_router)
    return app


@pytest_asyncio.fixture
async def http_env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await authz.init_authz(pool)
    async with pool.acquire() as conn:
        uid = await conn.fetchval(
            "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
            "VALUES ('a@t','x','A','admin') RETURNING id")
    # JWT minted while the user is admin; it never expires within the test.
    token = AuthService(pool, config).generate_access_token(uid, "a@t", "admin")
    app = _build_db_app(config)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        try:
            yield {"client": client, "pool": pool, "uid": uid,
                   "auth": {"Authorization": f"Bearer {token}"}}
        finally:
            await close_pool()


async def test_demotion_effective_next_request_despite_jwt(http_env):
    # Admin JWT still works while the row says admin.
    assert (await http_env["client"].get("/api/db/schemas", headers=http_env["auth"])).status_code == 200
    # Demote in the DB (role claim in the JWT is now stale).
    async with http_env["pool"].acquire() as conn:
        await conn.execute("UPDATE public.bh_users SET role='member' WHERE id=$1", http_env["uid"])
    # Next request with the SAME token is denied — live role read, not the JWT.
    assert (await http_env["client"].get("/api/db/schemas", headers=http_env["auth"])).status_code == 403


# === T-WS-1: deactivation over an open socket ==============================
class _DeactivateOnMessageWS:
    """Scripted socket that deactivates `user_id` in the DB at the moment it
    hands the handler the 'message' frame — modelling a deactivation that lands
    *after* the connect-time auth, while the socket is open."""

    def __init__(self, frames, pool, user_id):
        self._frames = list(frames)
        self._pool = pool
        self._user_id = user_id
        self.sent: list[dict] = []
        self.closed = None
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        if not self._frames:
            raise WebSocketDisconnect(code=1000)
        frame = self._frames.pop(0)
        if frame.get("type") == "message":
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "UPDATE public.bh_users SET is_active=false WHERE id=$1", self._user_id)
        return frame

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)

    def types(self):
        return [f.get("type") for f in self.sent]


@pytest_asyncio.fixture
async def ws_env(fresh_db, db_settings) -> AsyncIterator[dict]:
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO public.bh_users (id, email, password_hash, display_name, role, is_active) "
            "VALUES (1,'m@t','x','M','member',true)")
        await conn.execute(
            "INSERT INTO public.bh_conversations (id, workspace_id, user_id, title) "
            "VALUES (1,1,1,'C')")
    token = AuthService(pool, config).generate_access_token(1, "m@t", "member")
    try:
        yield {"config": config, "pool": pool, "token": token}
    finally:
        await close_pool()


async def test_deactivation_over_open_socket_rejected_next_message(ws_env):
    ws = _DeactivateOnMessageWS(
        [{"type": "auth", "token": ws_env["token"]},
         {"type": "message", "conversation_id": 1, "content": "hi", "model": "auto"}],
        ws_env["pool"], user_id=1,
    )
    await websocket_chat_handler(ws, WebSocketManager(), ws_env["config"], model_provider=None)

    # Auth succeeded at connect; the message frame triggered a re-load that saw
    # is_active=false → error + 4001 close, with no message persisted.
    assert "auth_success" in ws.types()
    assert "error" in ws.types()
    assert ws.closed is not None and ws.closed[0] == 4001
    async with ws_env["pool"].acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM public.bh_messages WHERE conversation_id=1")
    assert count == 0


# === T-WS-1: skill gate reflects live role =================================
async def test_skill_gate_reflects_live_role(ws_env):
    ex = SkillExecutor(ws_env["config"])
    member_gated = {"min_role": "member"}
    async with ws_env["pool"].acquire() as conn:
        # Explicit id: the fixture's id=1 insert left the serial sequence behind,
        # so an auto-id INSERT would collide on pkey.
        viewer_id = await conn.fetchval(
            "INSERT INTO public.bh_users (id, email, password_hash, display_name, role) "
            "VALUES (2,'v@t','x','V','viewer') RETURNING id")

    # Member passes the member-gated skill; viewer is denied.
    assert await ex._user_meets_min_role(member_gated, 1) is True
    assert await ex._user_meets_min_role(member_gated, viewer_id) is False

    # Demote user 1 member -> viewer; the very next gate check denies them (the
    # gate reads the live role each call — demotion effective next message).
    async with ws_env["pool"].acquire() as conn:
        await conn.execute("UPDATE public.bh_users SET role='viewer' WHERE id=1")
    assert await ex._user_meets_min_role(member_gated, 1) is False
