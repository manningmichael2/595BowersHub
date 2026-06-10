"""
Unit tests for POST /api/db/:schema/:table/import-csv endpoint (CSV import).

Tests the multipart upload, column mapping, value casting, constraint
violation handling, and result reporting.

Requirements: 30.4, 30.5, 30.6
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, patch, MagicMock

import asyncpg
import pytest

from backend.routers.db_browser import _cast_value, import_csv


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """Simulates an asyncpg Record with .items() and .keys() methods."""

    def items(self):
        return super().items()

    def keys(self):
        return super().keys()


class FakeUploadFile:
    """Simulates a FastAPI UploadFile."""

    def __init__(self, content: str, filename: str = "test.csv"):
        self._content = content.encode("utf-8")
        self.filename = filename

    async def read(self) -> bytes:
        return self._content


class MockConnection:
    """Simulates an asyncpg connection for testing import_csv."""

    def __init__(
        self,
        col_rows=None,
        execute_exceptions: dict[int, Exception] | None = None,
    ):
        self._col_rows = col_rows or []
        self._execute_exceptions = execute_exceptions or {}
        self._execute_count = 0

    async def fetch(self, sql: str, *args):
        """Returns column metadata rows."""
        return self._col_rows

    async def execute(self, sql: str, *args):
        """Simulates INSERT execution, raising per-row exceptions if configured."""
        self._execute_count += 1
        exc = self._execute_exceptions.get(self._execute_count)
        if exc:
            raise exc
        return "INSERT 0 1"


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
# Tests for _cast_value helper
# ---------------------------------------------------------------------------


class TestCastValue:
    """Tests for the _cast_value helper function."""

    def test_none_returns_none(self):
        assert _cast_value(None, "text") is None

    def test_empty_string_returns_none(self):
        assert _cast_value("", "text") is None
        assert _cast_value("   ", "integer") is None

    def test_boolean_true_values(self):
        assert _cast_value("true", "boolean") is True
        assert _cast_value("1", "boolean") is True
        assert _cast_value("yes", "boolean") is True
        assert _cast_value("t", "boolean") is True
        assert _cast_value("True", "boolean") is True

    def test_boolean_false_values(self):
        assert _cast_value("false", "boolean") is False
        assert _cast_value("0", "boolean") is False
        assert _cast_value("no", "boolean") is False
        assert _cast_value("anything_else", "boolean") is False

    def test_boolean_already_bool(self):
        assert _cast_value(True, "boolean") is True
        assert _cast_value(False, "boolean") is False

    def test_date_valid(self):
        result = _cast_value("2024-06-15", "date")
        assert result == date(2024, 6, 15)

    def test_date_with_time_suffix(self):
        result = _cast_value("2024-06-15T10:30:00", "date")
        assert result == date(2024, 6, 15)

    def test_date_invalid(self):
        assert _cast_value("not-a-date", "date") is None

    def test_timestamp_valid(self):
        result = _cast_value("2024-06-15T10:30:00", "timestamp with time zone")
        assert isinstance(result, datetime)
        assert result.year == 2024
        assert result.month == 6

    def test_timestamp_invalid(self):
        assert _cast_value("garbage", "timestamptz") is None

    def test_integer_valid(self):
        assert _cast_value("42", "integer") == 42
        assert _cast_value("0", "bigint") == 0
        assert _cast_value("-7", "smallint") == -7

    def test_integer_invalid(self):
        assert _cast_value("abc", "integer") is None
        assert _cast_value("3.14", "integer") is None

    def test_numeric_valid(self):
        result = _cast_value("3.14", "numeric")
        assert result == Decimal("3.14")

    def test_numeric_negative(self):
        result = _cast_value("-99.5", "double precision")
        assert result == Decimal("-99.5")

    def test_numeric_invalid(self):
        assert _cast_value("not_a_number", "numeric") is None

    def test_text_passthrough(self):
        assert _cast_value("hello", "text") == "hello"
        assert _cast_value("world", "character varying") == "world"

    def test_text_preserves_whitespace(self):
        assert _cast_value("  spaced  ", "text") == "  spaced  "


# ---------------------------------------------------------------------------
# Tests for import_csv endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_csv_success():
    """Successfully imports all rows from a CSV file."""
    csv_content = "name,brand,price\nDrill,DeWalt,199.99\nSaw,Festool,450.00\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name", "brand": "brand", "price": "purchase_price"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "brand", "data_type": "text"}),
        FakeRecord({"column_name": "purchase_price", "data_type": "numeric"}),
    ]
    conn = MockConnection(col_rows=col_rows)
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["total_rows"] == 2
    assert result["imported_rows"] == 2
    assert result["failed_rows"] == []


@pytest.mark.asyncio
async def test_import_csv_with_null_mapping_skips_columns():
    """Columns mapped to null are skipped during import."""
    csv_content = "name,notes,brand\nDrill,Some notes,DeWalt\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name", "notes": None, "brand": "brand"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "brand", "data_type": "text"}),
    ]
    conn = MockConnection(col_rows=col_rows)
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["total_rows"] == 1
    assert result["imported_rows"] == 1
    assert result["failed_rows"] == []


@pytest.mark.asyncio
async def test_import_csv_constraint_violation_continues():
    """Constraint violations are recorded and import continues."""
    csv_content = "name,brand\nDrill,DeWalt\nDrill,DeWalt\nSaw,Festool\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name", "brand": "brand"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "brand", "data_type": "text"}),
    ]

    # Second row (execute call #2) triggers unique violation
    exc = asyncpg.UniqueViolationError("duplicate key value")
    exc.detail = "Key (name)=(Drill) already exists."
    conn = MockConnection(col_rows=col_rows, execute_exceptions={2: exc})
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["total_rows"] == 3
    assert result["imported_rows"] == 2
    assert len(result["failed_rows"]) == 1
    assert result["failed_rows"][0]["line_number"] == 3  # CSV line 3 (header=1, row1=2, row2=3)
    assert "Unique violation" in result["failed_rows"][0]["error"]


@pytest.mark.asyncio
async def test_import_csv_not_null_violation():
    """NotNullViolationError is captured with column name."""
    csv_content = "name,brand\n,DeWalt\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name", "brand": "brand"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "brand", "data_type": "text"}),
    ]

    exc = asyncpg.NotNullViolationError("null value violates not-null constraint")
    exc.column_name = "name"
    conn = MockConnection(col_rows=col_rows, execute_exceptions={1: exc})
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["total_rows"] == 1
    assert result["imported_rows"] == 0
    assert len(result["failed_rows"]) == 1
    assert result["failed_rows"][0]["line_number"] == 2
    assert "name" in result["failed_rows"][0]["error"]
    assert "cannot be null" in result["failed_rows"][0]["error"]


@pytest.mark.asyncio
async def test_import_csv_fk_violation():
    """ForeignKeyViolationError is captured."""
    csv_content = "name,category_id\nDrill,999\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name", "category_id": "category_id"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "category_id", "data_type": "integer"}),
    ]

    exc = asyncpg.ForeignKeyViolationError("violates FK constraint")
    exc.detail = "Key (category_id)=(999) is not present in table categories."
    conn = MockConnection(col_rows=col_rows, execute_exceptions={1: exc})
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["total_rows"] == 1
    assert result["imported_rows"] == 0
    assert "Foreign key violation" in result["failed_rows"][0]["error"]


@pytest.mark.asyncio
async def test_import_csv_invalid_mapping_json():
    """Invalid JSON in mapping field returns 400."""
    from fastapi import HTTPException

    csv_content = "name\nDrill\n"
    file = FakeUploadFile(csv_content)
    mapping = "not valid json{"

    with pytest.raises(HTTPException) as exc_info:
        await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert exc_info.value.status_code == 400
    assert "Invalid mapping JSON" in exc_info.value.detail


@pytest.mark.asyncio
async def test_import_csv_empty_mapping():
    """Empty mapping dict returns 400."""
    from fastapi import HTTPException

    csv_content = "name\nDrill\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({})

    with pytest.raises(HTTPException) as exc_info:
        await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert exc_info.value.status_code == 400
    assert "cannot be empty" in exc_info.value.detail


@pytest.mark.asyncio
async def test_import_csv_all_columns_skipped():
    """Mapping with all null values returns 400."""
    from fastapi import HTTPException

    csv_content = "name,brand\nDrill,DeWalt\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": None, "brand": None})

    with pytest.raises(HTTPException) as exc_info:
        await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert exc_info.value.status_code == 400
    assert "skip" in exc_info.value.detail


@pytest.mark.asyncio
async def test_import_csv_missing_csv_column():
    """Mapping references a CSV column that doesn't exist in the file."""
    from fastapi import HTTPException

    csv_content = "name,brand\nDrill,DeWalt\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"nonexistent_col": "name"})

    with pytest.raises(HTTPException) as exc_info:
        await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert exc_info.value.status_code == 400
    assert "nonexistent_col" in exc_info.value.detail
    assert "not found in file headers" in exc_info.value.detail


@pytest.mark.asyncio
async def test_import_csv_missing_table_column():
    """Mapping references a table column that doesn't exist."""
    from fastapi import HTTPException

    csv_content = "name\nDrill\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "nonexistent_table_col"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
    ]
    conn = MockConnection(col_rows=col_rows)
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await import_csv(
                schema="inventory",
                table="tools",
                file=file,
                mapping=mapping,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 400
    assert "nonexistent_table_col" in exc_info.value.detail
    assert "does not exist" in exc_info.value.detail


@pytest.mark.asyncio
async def test_import_csv_table_not_found():
    """Returns 404 when table has no columns (doesn't exist)."""
    from fastapi import HTTPException

    csv_content = "name\nDrill\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name"})

    conn = MockConnection(col_rows=[])  # No columns = table not found
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await import_csv(
                schema="inventory",
                table="nonexistent",
                file=file,
                mapping=mapping,
                user={"id": 1, "role": "admin"},
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_import_csv_type_casting():
    """Values are cast to appropriate types based on column data_type."""
    csv_content = "name,count,price,active,acquired\nDrill,5,199.99,true,2024-01-15\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({
        "name": "name",
        "count": "quantity",
        "price": "purchase_price",
        "active": "is_active",
        "acquired": "acquired_at",
    })

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "quantity", "data_type": "integer"}),
        FakeRecord({"column_name": "purchase_price", "data_type": "numeric"}),
        FakeRecord({"column_name": "is_active", "data_type": "boolean"}),
        FakeRecord({"column_name": "acquired_at", "data_type": "date"}),
    ]

    # Track what values are passed to execute
    executed_values: list[tuple] = []

    class TrackingConnection(MockConnection):
        async def execute(self, sql: str, *args):
            executed_values.append(args)
            return "INSERT 0 1"

    conn = TrackingConnection(col_rows=col_rows)
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["imported_rows"] == 1

    # Check that values were properly cast
    values = executed_values[0]
    assert values[0] == "Drill"  # text
    assert values[1] == 5  # integer
    assert values[2] == Decimal("199.99")  # numeric
    assert values[3] is True  # boolean
    assert values[4] == date(2024, 1, 15)  # date


@pytest.mark.asyncio
async def test_import_csv_empty_cells_become_null():
    """Empty CSV cells are cast to None (NULL)."""
    csv_content = "name,brand\nDrill,\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name", "brand": "brand"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "brand", "data_type": "text"}),
    ]

    executed_values: list[tuple] = []

    class TrackingConnection(MockConnection):
        async def execute(self, sql: str, *args):
            executed_values.append(args)
            return "INSERT 0 1"

    conn = TrackingConnection(col_rows=col_rows)
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["imported_rows"] == 1
    values = executed_values[0]
    assert values[0] == "Drill"
    assert values[1] is None  # empty string → None


@pytest.mark.asyncio
async def test_import_csv_multiple_failures_collected():
    """Multiple rows can fail and all errors are collected."""
    csv_content = "name,brand\nA,X\nB,Y\nC,Z\nD,W\n"
    file = FakeUploadFile(csv_content)
    mapping = json.dumps({"name": "name", "brand": "brand"})

    col_rows = [
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "brand", "data_type": "text"}),
    ]

    # Rows 1 and 3 fail (execute calls 1 and 3)
    exc1 = asyncpg.UniqueViolationError("dup")
    exc1.detail = "Key (name)=(A) already exists."
    exc3 = asyncpg.CheckViolationError("check failed")
    exc3.constraint_name = "valid_name"

    conn = MockConnection(col_rows=col_rows, execute_exceptions={1: exc1, 3: exc3})
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await import_csv(
            schema="inventory",
            table="tools",
            file=file,
            mapping=mapping,
            user={"id": 1, "role": "admin"},
        )

    assert result["total_rows"] == 4
    assert result["imported_rows"] == 2
    assert len(result["failed_rows"]) == 2
    assert result["failed_rows"][0]["line_number"] == 2  # First data row
    assert result["failed_rows"][1]["line_number"] == 4  # Third data row
    assert "Unique violation" in result["failed_rows"][0]["error"]
    assert "Check constraint" in result["failed_rows"][1]["error"]
    assert "valid_name" in result["failed_rows"][1]["error"]
