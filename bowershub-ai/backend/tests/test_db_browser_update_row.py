"""
Unit tests for PATCH /api/db/:schema/:table/rows/:id endpoint (update row).

Tests the update logic, constraint violation handling, undo log writing,
and record serialization.

Requirements: 7.2, 7.3, 29.6
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch, MagicMock

import asyncpg
import pytest

from backend.routers.db_browser import _record_to_dict, _serialize_value


# ---------------------------------------------------------------------------
# Test helpers (same pattern as test_db_browser_create_row.py)
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """Simulates an asyncpg Record with .items() and .keys() methods."""

    def items(self):
        return super().items()

    def keys(self):
        return super().keys()


class MockRequest:
    """Simulates a FastAPI Request object with .json() and .headers."""

    def __init__(self, body: dict, headers: dict | None = None):
        self._body = body
        self.headers = headers or {}

    async def json(self):
        return self._body


class MockConnection:
    """Simulates an asyncpg connection for testing update_row."""

    def __init__(
        self,
        pk_rows=None,
        old_row=None,
        update_row=None,
        update_exception=None,
    ):
        self._pk_rows = pk_rows if pk_rows is not None else [FakeRecord({"column_name": "id"})]
        self._old_row = old_row
        self._update_row = update_row
        self._update_exception = update_exception
        self.executed_statements: list[tuple[str, tuple]] = []
        self._fetch_call_count = 0

    async def fetch(self, sql: str, *args):
        """Returns PK rows for the information_schema query."""
        return self._pk_rows

    async def fetchrow(self, sql: str, *args):
        """Handles both the old-row SELECT and the UPDATE ... RETURNING *."""
        self.executed_statements.append((sql, args))
        if "UPDATE" in sql:
            if self._update_exception:
                raise self._update_exception
            return self._update_row
        # SELECT for old row (undo log pre-fetch)
        return self._old_row

    async def execute(self, sql: str, *args):
        """Captures undo log INSERT."""
        self.executed_statements.append((sql, args))


class MockPoolCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockPool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return MockPoolCtx(self._conn)


# ---------------------------------------------------------------------------
# Tests for update_row endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_row_success():
    """Successfully updates a row and returns the serialized result."""
    from backend.routers.db_browser import update_row

    updated_row = FakeRecord({"id": 5, "name": "Updated Tool", "brand": "Festool"})
    conn = MockConnection(update_row=updated_row)
    pool = MockPool(conn)

    request = MockRequest({"name": "Updated Tool"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await update_row(
            schema="inventory",
            table="tools",
            row_id="5",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result == {"id": 5, "name": "Updated Tool", "brand": "Festool"}

    # Verify SQL uses quoted identifiers and parameterized values
    update_stmt = [s for s, _ in conn.executed_statements if "UPDATE" in s]
    assert len(update_stmt) == 1
    sql = update_stmt[0]
    assert '"inventory"."tools"' in sql
    assert '"name" = $1' in sql
    assert '"id" = $2' in sql
    assert "RETURNING *" in sql


@pytest.mark.asyncio
async def test_update_row_multiple_fields():
    """Updates multiple fields at once."""
    from backend.routers.db_browser import update_row

    updated_row = FakeRecord({"id": 3, "name": "Saw", "brand": "DeWalt", "price": Decimal("199.99")})
    conn = MockConnection(update_row=updated_row)
    pool = MockPool(conn)

    request = MockRequest({"name": "Saw", "brand": "DeWalt", "price": 199.99})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await update_row(
            schema="inventory",
            table="tools",
            row_id="3",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["name"] == "Saw"
    assert result["brand"] == "DeWalt"
    assert result["price"] == 199.99

    # Verify all three SET clauses in the SQL
    update_stmt = [s for s, _ in conn.executed_statements if "UPDATE" in s][0]
    assert "$1" in update_stmt
    assert "$2" in update_stmt
    assert "$3" in update_stmt
    assert "$4" in update_stmt  # PK param


@pytest.mark.asyncio
async def test_update_row_empty_body_returns_400():
    """Empty request body returns 400."""
    from backend.routers.db_browser import update_row
    from fastapi import HTTPException

    request = MockRequest({})

    with pytest.raises(HTTPException) as exc_info:
        await update_row(
            schema="inventory",
            table="tools",
            row_id="5",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert exc_info.value.status_code == 400
    assert "at least one field" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_row_not_found_returns_404():
    """Returns 404 when no row matches the PK value."""
    from backend.routers.db_browser import update_row
    from fastapi import HTTPException

    conn = MockConnection(update_row=None)
    pool = MockPool(conn)

    request = MockRequest({"name": "Ghost"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await update_row(
                schema="inventory",
                table="tools",
                row_id="9999",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_row_no_pk_returns_404():
    """Returns 404 when the table has no primary key."""
    from backend.routers.db_browser import update_row
    from fastapi import HTTPException

    conn = MockConnection(pk_rows=[])
    pool = MockPool(conn)

    request = MockRequest({"name": "Test"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await update_row(
                schema="inventory",
                table="tools",
                row_id="1",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 404
    assert "no primary key" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_row_unique_violation_returns_409():
    """UniqueViolationError is translated to 409 Conflict."""
    from backend.routers.db_browser import update_row
    from fastapi import HTTPException

    exc = asyncpg.UniqueViolationError("duplicate key value violates unique constraint")
    exc.detail = "Key (email)=(taken@example.com) already exists."
    conn = MockConnection(update_exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"email": "taken@example.com"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await update_row(
                schema="public",
                table="users",
                row_id="1",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 409
    assert "Duplicate value" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_row_fk_violation_returns_400():
    """ForeignKeyViolationError is translated to 400 Bad Request."""
    from backend.routers.db_browser import update_row
    from fastapi import HTTPException

    exc = asyncpg.ForeignKeyViolationError("violates foreign key constraint")
    exc.detail = "Key (category_id)=(999) is not present in table categories."
    conn = MockConnection(update_exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"category_id": 999})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await update_row(
                schema="public",
                table="items",
                row_id="1",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 400
    assert "Foreign key violation" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_row_not_null_violation_returns_400():
    """NotNullViolationError is translated to 400 with column name."""
    from backend.routers.db_browser import update_row
    from fastapi import HTTPException

    exc = asyncpg.NotNullViolationError("null value violates not-null constraint")
    exc.column_name = "brand"
    conn = MockConnection(update_exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"brand": None})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await update_row(
                schema="inventory",
                table="tools",
                row_id="1",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 400
    assert "brand" in exc_info.value.detail
    assert "cannot be null" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_row_check_violation_returns_400():
    """CheckViolationError is translated to 400 with constraint name."""
    from backend.routers.db_browser import update_row
    from fastapi import HTTPException

    exc = asyncpg.CheckViolationError("new row violates check constraint")
    exc.constraint_name = "positive_price"
    conn = MockConnection(update_exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"price": -5.0})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await update_row(
                schema="inventory",
                table="tools",
                row_id="1",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 400
    assert "positive_price" in exc_info.value.detail
    assert "Check constraint" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_row_undo_log_written_when_session_header_present():
    """When X-DB-Session-Id header is present, writes undo log entry."""
    from backend.routers.db_browser import update_row

    old_row = FakeRecord({"id": 5, "name": "Old Name", "brand": "Festool"})
    updated_row = FakeRecord({"id": 5, "name": "New Name", "brand": "Festool"})
    conn = MockConnection(old_row=old_row, update_row=updated_row)
    pool = MockPool(conn)

    request = MockRequest(
        body={"name": "New Name"},
        headers={"x-db-session-id": "session-abc-123"},
    )

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await update_row(
            schema="inventory",
            table="tools",
            row_id="5",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["name"] == "New Name"

    # Verify undo log INSERT was executed
    undo_stmts = [
        (s, a) for s, a in conn.executed_statements if "bh_db_browser_undo_log" in s
    ]
    assert len(undo_stmts) == 1
    undo_sql, undo_args = undo_stmts[0]
    assert "INSERT INTO bh_db_browser_undo_log" in undo_sql
    assert undo_args[0] == "session-abc-123"  # session_id
    assert undo_args[1] == "1"  # user_id
    assert undo_args[2] == "inventory"  # schema_name
    assert undo_args[3] == "tools"  # table_name
    assert undo_args[4] == "5"  # row_id
    assert undo_args[5] == "update"  # operation_type
    # previous_values should be the old row as JSON
    prev_values = json.loads(undo_args[6])
    assert prev_values["name"] == "Old Name"
    # new_values should be only the updated fields
    new_values = json.loads(undo_args[7])
    assert new_values == {"name": "New Name"}


@pytest.mark.asyncio
async def test_update_row_no_undo_log_without_session_header():
    """When X-DB-Session-Id header is absent, no undo log is written."""
    from backend.routers.db_browser import update_row

    updated_row = FakeRecord({"id": 5, "name": "Updated", "brand": "Festool"})
    conn = MockConnection(update_row=updated_row)
    pool = MockPool(conn)

    request = MockRequest(body={"name": "Updated"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await update_row(
            schema="inventory",
            table="tools",
            row_id="5",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["name"] == "Updated"

    # No undo log INSERT should have been executed
    undo_stmts = [
        (s, a) for s, a in conn.executed_statements if "bh_db_browser_undo_log" in s
    ]
    assert len(undo_stmts) == 0


@pytest.mark.asyncio
async def test_update_row_integer_pk_cast():
    """Row ID string is cast to int when possible for PK lookup."""
    from backend.routers.db_browser import update_row

    updated_row = FakeRecord({"id": 42, "name": "Test"})
    conn = MockConnection(update_row=updated_row)
    pool = MockPool(conn)

    request = MockRequest({"name": "Test"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await update_row(
            schema="inventory",
            table="tools",
            row_id="42",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    # The UPDATE should have been called with integer 42 as the PK param
    update_stmts = [(s, a) for s, a in conn.executed_statements if "UPDATE" in s]
    assert len(update_stmts) == 1
    _, args = update_stmts[0]
    # Last arg is the PK value
    assert args[-1] == 42


@pytest.mark.asyncio
async def test_update_row_uuid_pk_kept_as_string():
    """Row ID that's not an integer is kept as string (for UUID PKs)."""
    from backend.routers.db_browser import update_row

    uid = "abcdef12-3456-7890-abcd-ef1234567890"
    updated_row = FakeRecord({"id": uid, "name": "Test"})
    conn = MockConnection(update_row=updated_row)
    pool = MockPool(conn)

    request = MockRequest({"name": "Test"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await update_row(
            schema="public",
            table="items",
            row_id=uid,
            request=request,
            user={"id": 1, "role": "admin"},
        )

    # The UPDATE should have been called with the string UUID as the PK param
    update_stmts = [(s, a) for s, a in conn.executed_statements if "UPDATE" in s]
    _, args = update_stmts[0]
    assert args[-1] == uid
