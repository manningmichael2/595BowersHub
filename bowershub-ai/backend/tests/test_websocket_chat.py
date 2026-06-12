"""
DB-backed e2e tests for the WebSocket chat handler.

project-review.md C5: "the WebSocket chat handlers (the primary UX)" had no
tests. This suite drives `backend.websocket.handlers` against a real Postgres
schema with a scripted fake WebSocket — no live socket, no network.

Two layers are covered:
  - `websocket_chat_handler`  — the auth handshake + message-loop protocol
    (first-message-must-be-auth, invalid token, auth_success, ping/pong,
    unknown type). Fully hermetic.
  - `handle_chat_message`     — the message write-path: loads conversation +
    workspace, persists the user + assistant messages, and emits typing /
    complete frames. Driven with a `/help` message so routing stays at L1 and
    no model provider is ever called.

Validates the WebSocket half of project-review.md C5.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import WebSocketDisconnect

from backend.config import Config
from backend.database import close_pool, get_pool, init_pool, run_migrations
from backend.services.auth import AuthService
from backend.websocket.handlers import handle_chat_message, websocket_chat_handler
from backend.websocket.manager import WebSocketManager

pytestmark = pytest.mark.asyncio


def _config(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-at-least-32-bytes-long!!",
        N8N_BASE="http://localhost:5678",
    )


class FakeWebSocket:
    """Scripted WebSocket: yields `incoming` frames in order, then raises
    WebSocketDisconnect to end the handler's receive loop. Records everything
    sent and whether/how it was closed."""

    def __init__(self, incoming=None):
        self._incoming = list(incoming or [])
        self.sent: list[dict] = []
        self.closed: tuple | None = None
        self.accepted = False

    async def accept(self):
        self.accepted = True

    async def receive_json(self):
        if not self._incoming:
            raise WebSocketDisconnect(code=1000)
        return self._incoming.pop(0)

    async def send_json(self, data):
        self.sent.append(data)

    async def close(self, code=1000, reason=""):
        self.closed = (code, reason)

    def types(self):
        return [f.get("type") for f in self.sent]


class RecordingWSManager:
    """Records the high-level frames handle_chat_message emits via the manager."""

    def __init__(self):
        self.typing: list = []
        self.errors: list = []
        self.completes: list = []

    async def send_typing(self, user_id, conversation_id):
        self.typing.append((user_id, conversation_id))

    async def send_error(self, user_id, conversation_id, message):
        self.errors.append((user_id, conversation_id, message))

    async def send_complete(self, user_id, conversation_id, message):
        self.completes.append((user_id, conversation_id, message))


class NoCallProvider:
    async def complete(self, *args, **kwargs):
        raise AssertionError("a /help message must not reach the model provider")


async def _seed_user_and_conversation(pool):
    """Insert one active member + a conversation in the seeded 'General' (ws 1)."""
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.bh_users (id, email, password_hash, display_name, role, is_active)
            VALUES (1, 'tester@example.com', 'x', 'Tester', 'member', true)
            """
        )
        await conn.execute(
            """
            INSERT INTO public.bh_conversations (id, workspace_id, user_id, title)
            VALUES (1, 1, 1, 'Test conversation')
            """
        )


@pytest_asyncio.fixture
async def ws_env(fresh_db, db_settings):
    """Schema + a seeded user/conversation; yields (config, user_dict)."""
    config = _config(fresh_db, db_settings)
    pool = await init_pool(config)
    await run_migrations(pool)
    await _seed_user_and_conversation(pool)
    user = {"id": 1, "email": "tester@example.com", "role": "member", "is_active": True}
    try:
        yield config, user
    finally:
        await close_pool()


# --- handle_chat_message: the message write-path ----------------------------


async def test_help_message_persists_and_completes(ws_env):
    """A /help message: persists user + assistant rows, emits typing+complete,
    routes at L1 with no model call."""
    config, user = ws_env
    manager = RecordingWSManager()
    ws = FakeWebSocket()

    await handle_chat_message(
        data={"type": "message", "conversation_id": 1, "content": "/help", "model": "auto"},
        user=user,
        websocket=ws,
        ws_manager=manager,
        config=config,
        model_provider=NoCallProvider(),
    )

    # Frames: typing started, then a complete with the help listing.
    assert manager.typing == [(1, 1)]
    assert len(manager.completes) == 1
    _, _, complete_msg = manager.completes[0]
    assert complete_msg["routing_layer"] == "L1"
    assert "/help" in complete_msg["content"]
    assert manager.errors == []

    # Persistence: one user row, one assistant row tagged L1.
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT role, content, routing_layer FROM public.bh_messages "
            "WHERE conversation_id = 1 ORDER BY id"
        )
    assert [r["role"] for r in rows] == ["user", "assistant"]
    assert rows[0]["content"] == "/help"
    assert rows[1]["routing_layer"] == "L1"


async def test_empty_content_rejected_without_persisting(ws_env):
    config, user = ws_env
    manager = RecordingWSManager()
    ws = FakeWebSocket()

    await handle_chat_message(
        data={"type": "message", "conversation_id": 1, "content": "   ", "model": "auto"},
        user=user,
        websocket=ws,
        ws_manager=manager,
        config=config,
        model_provider=NoCallProvider(),
    )

    assert ws.types() == ["error"]
    assert "empty" in ws.sent[0]["data"]["message"].lower()
    pool = get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("SELECT count(*) FROM public.bh_messages")
    assert count == 0


async def test_overlong_content_rejected(ws_env):
    config, user = ws_env
    manager = RecordingWSManager()
    ws = FakeWebSocket()

    await handle_chat_message(
        data={"type": "message", "conversation_id": 1, "content": "x" * 10001, "model": "auto"},
        user=user,
        websocket=ws,
        ws_manager=manager,
        config=config,
        model_provider=NoCallProvider(),
    )

    assert ws.types() == ["error"]
    assert "too long" in ws.sent[0]["data"]["message"].lower()


async def test_unknown_conversation_sends_error(ws_env):
    config, user = ws_env
    manager = RecordingWSManager()
    ws = FakeWebSocket()

    await handle_chat_message(
        data={"type": "message", "conversation_id": 99999, "content": "hello", "model": "auto"},
        user=user,
        websocket=ws,
        ws_manager=manager,
        config=config,
        model_provider=NoCallProvider(),
    )

    assert len(manager.errors) == 1
    assert "Conversation not found" in manager.errors[0][2]


# --- websocket_chat_handler: the auth handshake + protocol ------------------


async def test_first_message_must_be_auth(ws_env):
    config, _ = ws_env
    ws = FakeWebSocket([{"type": "message", "content": "hi"}])

    await websocket_chat_handler(ws, WebSocketManager(), config, model_provider=None)

    assert ws.accepted is True
    assert "error" in ws.types()
    assert ws.closed is not None and ws.closed[0] == 4001


async def test_invalid_token_rejected(ws_env):
    config, _ = ws_env
    ws = FakeWebSocket([{"type": "auth", "token": "not-a-real-jwt"}])

    await websocket_chat_handler(ws, WebSocketManager(), config, model_provider=None)

    assert "error" in ws.types()
    assert "Invalid or expired token" in ws.sent[0]["data"]["message"]
    assert ws.closed is not None and ws.closed[0] == 4001


async def test_valid_token_authenticates_then_ping_pong(ws_env):
    config, user = ws_env
    token = AuthService(get_pool(), config).generate_access_token(
        user["id"], user["email"], user["role"]
    )
    ws = FakeWebSocket([{"type": "auth", "token": token}, {"type": "ping"}])

    await websocket_chat_handler(ws, WebSocketManager(), config, model_provider=None)

    types = ws.types()
    assert "auth_success" in types
    assert "pong" in types
    auth_frame = next(f for f in ws.sent if f["type"] == "auth_success")
    assert auth_frame["data"]["user_id"] == 1


async def test_unknown_message_type_after_auth(ws_env):
    config, user = ws_env
    token = AuthService(get_pool(), config).generate_access_token(
        user["id"], user["email"], user["role"]
    )
    ws = FakeWebSocket([{"type": "auth", "token": token}, {"type": "bogus"}])

    await websocket_chat_handler(ws, WebSocketManager(), config, model_provider=None)

    errors = [f for f in ws.sent if f["type"] == "error"]
    assert any("Unknown message type" in f["data"]["message"] for f in errors)
