"""
Unit tests for POST /api/db/:schema/:table/rows endpoint (create row).

Tests the insert logic, constraint violation handling, and record serialization.

Requirements: 12.3, 12.4
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch, MagicMock

import asyncpg
import pytest
import pytest_asyncio

from backend.routers.db_browser import _record_to_dict, _serialize_value


# ---------------------------------------------------------------------------
# Tests for _record_to_dict / _serialize_value helper
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """Simulates an asyncpg Record with .items() method."""

    def items(self):
        return super().items()


class TestSerializeValue:
    """Test the _serialize_value helper function."""

    def test_none(self):
        assert _serialize_value(None) is None

    def test_uuid(self):
        u = uuid.UUID("12345678-1234-5678-1234-567812345678")
        assert _serialize_value(u) == "12345678-1234-5678-1234-567812345678"

    def test_datetime(self):
        dt = datetime(2026, 6, 7, 14, 30, 0)
        assert _serialize_value(dt) == "2026-06-07T14:30:00"

    def test_date(self):
        d = date(2026, 6, 7)
        assert _serialize_value(d) == "2026-06-07"

    def test_time(self):
        t = time(14, 30, 0)
        assert _serialize_value(t) == "14:30:00"

    def test_timedelta(self):
        td = timedelta(hours=2, minutes=30)
        assert _serialize_value(td) == 9000.0

    def test_decimal(self):
        d = Decimal("3.14159")
        assert _serialize_value(d) == 3.14159

    def test_bytes(self):
        b = b"\xde\xad\xbe\xef"
        assert _serialize_value(b) == "deadbeef"

    def test_list(self):
        result = _serialize_value([uuid.UUID("12345678-1234-5678-1234-567812345678"), 42])
        assert result == ["12345678-1234-5678-1234-567812345678", 42]

    def test_nested_dict(self):
        result = _serialize_value({"amount": Decimal("9.99"), "note": "test"})
        assert result == {"amount": 9.99, "note": "test"}

    def test_plain_types_passthrough(self):
        assert _serialize_value(42) == 42
        assert _serialize_value(3.14) == 3.14
        assert _serialize_value("hello") == "hello"
        assert _serialize_value(True) is True
        assert _serialize_value(False) is False


class TestRecordToDict:
    """Test the _record_to_dict helper function."""

    def test_basic_record(self):
        record = FakeRecord({"id": 1, "name": "Test", "price": Decimal("19.99")})
        result = _record_to_dict(record)
        assert result == {"id": 1, "name": "Test", "price": 19.99}

    def test_record_with_uuid_and_datetime(self):
        uid = uuid.UUID("abcdef12-3456-7890-abcd-ef1234567890")
        dt = datetime(2026, 1, 15, 10, 0, 0)
        record = FakeRecord({"id": uid, "created_at": dt, "name": "Widget"})
        result = _record_to_dict(record)
        assert result == {
            "id": "abcdef12-3456-7890-abcd-ef1234567890",
            "created_at": "2026-01-15T10:00:00",
            "name": "Widget",
        }

    def test_record_with_none_values(self):
        record = FakeRecord({"id": 5, "notes": None, "category": None})
        result = _record_to_dict(record)
        assert result == {"id": 5, "notes": None, "category": None}


# ---------------------------------------------------------------------------
# Tests for the create_row endpoint
# ---------------------------------------------------------------------------


class MockRequest:
    """Simulates a FastAPI Request object with a .json() method."""

    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


class MockConnection:
    """Simulates an asyncpg connection for testing."""

    def __init__(self, return_row=None, exception=None):
        self._return_row = return_row
        self._exception = exception
        self.last_sql = None
        self.last_args = None

    async def fetchrow(self, sql: str, *args):
        self.last_sql = sql
        self.last_args = args
        if self._exception:
            raise self._exception
        return self._return_row


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


@pytest.mark.asyncio
async def test_create_row_success():
    """Successfully inserts a row and returns the serialized result."""
    from backend.routers.db_browser import create_row

    return_row = FakeRecord({"id": 42, "name": "New Tool", "brand": "Festool"})
    conn = MockConnection(return_row=return_row)
    pool = MockPool(conn)

    request = MockRequest({"name": "New Tool", "brand": "Festool"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await create_row(
            schema="inventory",
            table="tools",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result == {"id": 42, "name": "New Tool", "brand": "Festool"}
    # Verify SQL uses quoted identifiers and parameterized values
    assert '"inventory"."tools"' in conn.last_sql
    assert '"name"' in conn.last_sql
    assert '"brand"' in conn.last_sql
    assert "$1" in conn.last_sql
    assert "$2" in conn.last_sql
    assert "RETURNING *" in conn.last_sql
    assert conn.last_args == ("New Tool", "Festool")


@pytest.mark.asyncio
async def test_create_row_empty_body_returns_400():
    """Empty request body returns 400."""
    from backend.routers.db_browser import create_row
    from fastapi import HTTPException

    request = MockRequest({})

    with pytest.raises(HTTPException) as exc_info:
        await create_row(
            schema="inventory",
            table="tools",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert exc_info.value.status_code == 400
    assert "at least one field" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_row_unique_violation_returns_409():
    """UniqueViolationError is translated to 409 Conflict."""
    from backend.routers.db_browser import create_row
    from fastapi import HTTPException

    exc = asyncpg.UniqueViolationError(
        "duplicate key value violates unique constraint"
    )
    # asyncpg exceptions store detail via message parsing; simulate with a basic exception
    exc.detail = "Key (email)=(test@example.com) already exists."
    conn = MockConnection(exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"email": "test@example.com"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await create_row(
                schema="public",
                table="users",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 409
    assert "Duplicate value" in exc_info.value.detail
    assert "already exists" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_row_fk_violation_returns_400():
    """ForeignKeyViolationError is translated to 400 Bad Request."""
    from backend.routers.db_browser import create_row
    from fastapi import HTTPException

    exc = asyncpg.ForeignKeyViolationError(
        "insert or update violates foreign key constraint"
    )
    exc.detail = "Key (category_id)=(999) is not present in table categories."
    conn = MockConnection(exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"name": "Test", "category_id": 999})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await create_row(
                schema="public",
                table="items",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 400
    assert "Foreign key violation" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_row_not_null_violation_returns_400():
    """NotNullViolationError is translated to 400 with column name."""
    from backend.routers.db_browser import create_row
    from fastapi import HTTPException

    exc = asyncpg.NotNullViolationError(
        "null value in column violates not-null constraint"
    )
    exc.column_name = "brand"
    conn = MockConnection(exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"name": "Test"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await create_row(
                schema="inventory",
                table="tools",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 400
    assert "brand" in exc_info.value.detail
    assert "cannot be null" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_row_check_violation_returns_400():
    """CheckViolationError is translated to 400 with constraint name."""
    from backend.routers.db_browser import create_row
    from fastapi import HTTPException

    exc = asyncpg.CheckViolationError(
        "new row violates check constraint"
    )
    exc.constraint_name = "positive_price"
    conn = MockConnection(exception=exc)
    pool = MockPool(conn)

    request = MockRequest({"price": -5.0})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await create_row(
                schema="inventory",
                table="tools",
                request=request,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 400
    assert "positive_price" in exc_info.value.detail
    assert "Check constraint" in exc_info.value.detail


@pytest.mark.asyncio
async def test_create_row_serializes_complex_types():
    """Returned row with UUID, Decimal, datetime is properly serialized."""
    from backend.routers.db_browser import create_row

    uid = uuid.UUID("aaaabbbb-cccc-dddd-eeee-ffffffffffff")
    return_row = FakeRecord({
        "id": uid,
        "price": Decimal("49.99"),
        "created_at": datetime(2026, 6, 7, 12, 0, 0),
        "name": "Router Bit",
    })
    conn = MockConnection(return_row=return_row)
    pool = MockPool(conn)

    request = MockRequest({"name": "Router Bit", "price": 49.99})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await create_row(
            schema="inventory",
            table="router_bits",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["id"] == "aaaabbbb-cccc-dddd-eeee-ffffffffffff"
    assert result["price"] == 49.99
    assert result["created_at"] == "2026-06-07T12:00:00"
    assert result["name"] == "Router Bit"


@pytest.mark.asyncio
async def test_create_row_sql_uses_parameterized_queries():
    """SQL injection via column names or values is prevented."""
    from backend.routers.db_browser import create_row

    return_row = FakeRecord({"id": 1, "notes": "test'; DROP TABLE tools; --"})
    conn = MockConnection(return_row=return_row)
    pool = MockPool(conn)

    request = MockRequest({"notes": "test'; DROP TABLE tools; --"})

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await create_row(
            schema="inventory",
            table="tools",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    # Values are passed as parameters, not interpolated into SQL
    assert conn.last_args == ("test'; DROP TABLE tools; --",)
    assert "$1" in conn.last_sql
