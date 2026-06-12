"""
DB-backed integration tests for db_browser undo logging + mutation atomicity.

project-review.md C4 flagged that mutations and their undo-log writes were not
atomic. Investigation found the undo writes were in fact *dead*: the code passed
``str(user_id)`` into the ``user_id integer NOT NULL`` column, so every insert
raised asyncpg.DataError and was swallowed by a ``try/except … warning`` — no
undo row was ever recorded through update/delete/bulk paths.

These tests run against a real Postgres schema (built from the squashed baseline)
and prove the fix end-to-end:
  - an undo row is now actually written, with correct uuid/int types;
  - a failed undo write rolls the data change back (atomicity);
  - an invalid session header skips undo without failing the mutation.

Validates project-review.md C4 (atomicity + the undo repair).
"""

from __future__ import annotations

import uuid

import pytest

from backend.config import Config
from backend.database import close_pool, get_pool, init_pool, run_migrations
from backend.routers.db_browser import delete_row, update_row

pytestmark = pytest.mark.asyncio

_SESSION = "11111111-2222-3333-4444-555555555555"
_ADMIN = {"id": 1, "role": "admin"}


class _Req:
    """Minimal Request stand-in: update_row/delete_row use .json() + .headers."""

    def __init__(self, body=None, headers=None):
        self._body = body or {}
        self.headers = headers or {}

    async def json(self):
        return self._body


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


async def _setup(fresh_db, db_settings):
    """Build the schema and a tiny target table with one row; return its id."""
    pool = await init_pool(_config(fresh_db, db_settings))
    await run_migrations(pool)
    async with pool.acquire() as conn:
        # The undo log's user_id has a FK to bh_users — seed the acting admin.
        await conn.execute(
            """
            INSERT INTO public.bh_users (id, email, password_hash, display_name, role, is_active)
            VALUES (1, 'admin@example.com', 'x', 'Admin', 'admin', true)
            """
        )
        await conn.execute(
            """
            CREATE TABLE public.t (
                id SERIAL PRIMARY KEY,
                name TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        row_id = await conn.fetchval("INSERT INTO public.t (name) VALUES ('old') RETURNING id")
    return pool, row_id


async def test_update_writes_undo_row(fresh_db, db_settings):
    """A session-tracked update now records a real undo row (was always swallowed)."""
    pool, row_id = await _setup(fresh_db, db_settings)
    try:
        req = _Req({"name": "new"}, {"x-db-session-id": _SESSION})
        result = await update_row("public", "t", str(row_id), req, user=_ADMIN)
        assert result["name"] == "new"

        async with pool.acquire() as conn:
            undo = await conn.fetchrow(
                "SELECT * FROM bh_db_browser_undo_log WHERE session_id = $1",
                uuid.UUID(_SESSION),
            )
        assert undo is not None, "undo row should have been written"
        assert undo["user_id"] == 1
        assert undo["operation_type"] == "update"
        assert undo["table_name"] == "t"
        assert undo["previous_values"]["name"] == "old"
        assert undo["new_values"] == {"name": "new"}
    finally:
        await close_pool()


async def test_update_rolls_back_when_undo_write_fails(fresh_db, db_settings):
    """If the undo insert fails, the data change must roll back (atomicity)."""
    pool, row_id = await _setup(fresh_db, db_settings)
    try:
        # Break the undo target so the undo INSERT raises inside the transaction.
        async with pool.acquire() as conn:
            await conn.execute("DROP TABLE bh_db_browser_undo_log")

        req = _Req({"name": "should_not_persist"}, {"x-db-session-id": _SESSION})
        with pytest.raises(Exception):
            await update_row("public", "t", str(row_id), req, user=_ADMIN)

        async with pool.acquire() as conn:
            current = await conn.fetchval("SELECT name FROM public.t WHERE id = $1", row_id)
        assert current == "old", "the update must have rolled back with the failed undo"
    finally:
        await close_pool()


async def test_invalid_session_skips_undo_but_update_succeeds(fresh_db, db_settings):
    """A malformed session header is ignored for undo and does NOT fail the edit."""
    pool, row_id = await _setup(fresh_db, db_settings)
    try:
        req = _Req({"name": "new"}, {"x-db-session-id": "not-a-uuid"})
        result = await update_row("public", "t", str(row_id), req, user=_ADMIN)
        assert result["name"] == "new"

        async with pool.acquire() as conn:
            count = await conn.fetchval("SELECT count(*) FROM bh_db_browser_undo_log")
        assert count == 0, "no undo row for an invalid session header"
    finally:
        await close_pool()


async def test_delete_writes_undo_row(fresh_db, db_settings):
    """delete_row records its undo entry with the deleted row's full state."""
    pool, row_id = await _setup(fresh_db, db_settings)
    try:
        req = _Req(headers={"x-db-session-id": _SESSION})
        result = await delete_row("public", "t", str(row_id), req, user=_ADMIN)
        assert result["ok"] is True

        async with pool.acquire() as conn:
            undo = await conn.fetchrow(
                "SELECT * FROM bh_db_browser_undo_log WHERE session_id = $1",
                uuid.UUID(_SESSION),
            )
            still_there = await conn.fetchval("SELECT count(*) FROM public.t WHERE id = $1", row_id)
        assert still_there == 0
        assert undo is not None and undo["operation_type"] == "delete"
        assert undo["previous_values"]["name"] == "old"
    finally:
        await close_pool()
