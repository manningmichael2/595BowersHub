"""
Unit tests for GET /api/db/:schema/:table/lookup-options/:column endpoint.

Tests the FK lookup, display column resolution, search filtering, and error handling.

Requirements: 17.4, 17.5
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import pytest

from backend.routers.db_browser import get_lookup_options


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """Simulates an asyncpg Record with .items() method."""

    def items(self):
        return super().items()


class MockConnection:
    """Simulates an asyncpg connection with configurable return values per call."""

    def __init__(self, call_results: list | None = None):
        self._call_results = call_results or []
        self._call_index = 0
        self.calls: list[tuple[str, tuple]] = []

    async def fetchrow(self, sql: str, *args):
        self.calls.append((sql, args))
        if self._call_index < len(self._call_results):
            result = self._call_results[self._call_index]
            self._call_index += 1
            return result
        return None

    async def fetch(self, sql: str, *args):
        self.calls.append((sql, args))
        if self._call_index < len(self._call_results):
            result = self._call_results[self._call_index]
            self._call_index += 1
            return result
        return []


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
# Tests: No FK constraint (404)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_options_no_fk_returns_404():
    """Column without FK constraint returns 404."""
    from fastapi import HTTPException

    # fetchrow returns None = no FK found
    conn = MockConnection(call_results=[None])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        with pytest.raises(HTTPException) as exc_info:
            await get_lookup_options(
                schema="inventory",
                table="tools",
                column="brand",
                search=None,
                user={"id": 1},
            )

    assert exc_info.value.status_code == 404
    assert "no foreign key constraint" in exc_info.value.detail


# ---------------------------------------------------------------------------
# Tests: Display column resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_options_uses_name_column():
    """When referenced table has a 'name' column, uses it as display."""
    fk_row = FakeRecord({
        "ref_schema": "inventory",
        "ref_table": "brands",
        "ref_column": "id",
    })
    col_rows = [
        FakeRecord({"column_name": "id", "data_type": "integer"}),
        FakeRecord({"column_name": "name", "data_type": "text"}),
        FakeRecord({"column_name": "website", "data_type": "text"}),
    ]
    options_rows = [
        FakeRecord({"id": 1, "label": "DeWalt"}),
        FakeRecord({"id": 2, "label": "Festool"}),
    ]

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="inventory",
            table="tools",
            column="brand_id",
            search=None,
            user={"id": 1},
        )

    assert result == [
        {"id": 1, "label": "DeWalt"},
        {"id": 2, "label": "Festool"},
    ]
    # Verify the final query uses "name" as the display column
    final_sql = conn.calls[-1][0]
    assert '"name"' in final_sql
    assert "LIMIT 500" in final_sql


@pytest.mark.asyncio
async def test_lookup_options_uses_title_when_no_name():
    """When referenced table has 'title' but no 'name', uses 'title'."""
    fk_row = FakeRecord({
        "ref_schema": "cook",
        "ref_table": "recipes",
        "ref_column": "id",
    })
    col_rows = [
        FakeRecord({"column_name": "id", "data_type": "integer"}),
        FakeRecord({"column_name": "title", "data_type": "text"}),
        FakeRecord({"column_name": "instructions", "data_type": "text"}),
    ]
    options_rows = [
        FakeRecord({"id": 1, "label": "Pancakes"}),
    ]

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="cook",
            table="cook_log",
            column="recipe_id",
            search=None,
            user={"id": 1},
        )

    assert result == [{"id": 1, "label": "Pancakes"}]
    final_sql = conn.calls[-1][0]
    assert '"title"' in final_sql


@pytest.mark.asyncio
async def test_lookup_options_falls_back_to_first_text_column():
    """When no name/title/description, uses first text column."""
    fk_row = FakeRecord({
        "ref_schema": "public",
        "ref_table": "categories",
        "ref_column": "id",
    })
    col_rows = [
        FakeRecord({"column_name": "id", "data_type": "integer"}),
        FakeRecord({"column_name": "code", "data_type": "character varying"}),
        FakeRecord({"column_name": "sort_order", "data_type": "integer"}),
    ]
    options_rows = [
        FakeRecord({"id": 1, "label": "FOOD"}),
        FakeRecord({"id": 2, "label": "TRANSPORT"}),
    ]

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="public",
            table="transactions",
            column="category_id",
            search=None,
            user={"id": 1},
        )

    assert result == [
        {"id": 1, "label": "FOOD"},
        {"id": 2, "label": "TRANSPORT"},
    ]
    final_sql = conn.calls[-1][0]
    assert '"code"' in final_sql


@pytest.mark.asyncio
async def test_lookup_options_falls_back_to_pk_column():
    """When no text columns exist, uses the PK column as display."""
    fk_row = FakeRecord({
        "ref_schema": "public",
        "ref_table": "statuses",
        "ref_column": "id",
    })
    col_rows = [
        FakeRecord({"column_name": "id", "data_type": "integer"}),
        FakeRecord({"column_name": "sort_order", "data_type": "integer"}),
        FakeRecord({"column_name": "is_active", "data_type": "boolean"}),
    ]
    options_rows = [
        FakeRecord({"id": 1, "label": 1}),
        FakeRecord({"id": 2, "label": 2}),
    ]

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="public",
            table="items",
            column="status_id",
            search=None,
            user={"id": 1},
        )

    assert result == [{"id": 1, "label": 1}, {"id": 2, "label": 2}]


# ---------------------------------------------------------------------------
# Tests: Search filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_options_with_search_filters_and_limits():
    """Search param adds ILIKE filter and limits to 50."""
    fk_row = FakeRecord({
        "ref_schema": "inventory",
        "ref_table": "brands",
        "ref_column": "id",
    })
    col_rows = [
        FakeRecord({"column_name": "id", "data_type": "integer"}),
        FakeRecord({"column_name": "name", "data_type": "text"}),
    ]
    options_rows = [
        FakeRecord({"id": 2, "label": "Festool"}),
    ]

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="inventory",
            table="tools",
            column="brand_id",
            search="fest",
            user={"id": 1},
        )

    assert result == [{"id": 2, "label": "Festool"}]
    # Verify search query uses ILIKE and LIMIT 50
    final_sql = conn.calls[-1][0]
    assert "ILIKE" in final_sql
    assert "LIMIT 50" in final_sql
    # Verify parameterized search value
    final_args = conn.calls[-1][1]
    assert final_args == ("%fest%",)


@pytest.mark.asyncio
async def test_lookup_options_empty_search_treated_as_no_search():
    """Empty or whitespace-only search is treated as no search."""
    fk_row = FakeRecord({
        "ref_schema": "inventory",
        "ref_table": "brands",
        "ref_column": "id",
    })
    col_rows = [
        FakeRecord({"column_name": "id", "data_type": "integer"}),
        FakeRecord({"column_name": "name", "data_type": "text"}),
    ]
    options_rows = [
        FakeRecord({"id": 1, "label": "DeWalt"}),
        FakeRecord({"id": 2, "label": "Festool"}),
    ]

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="inventory",
            table="tools",
            column="brand_id",
            search="   ",
            user={"id": 1},
        )

    assert len(result) == 2
    # Should use LIMIT 500 (no search), not LIMIT 50
    final_sql = conn.calls[-1][0]
    assert "ILIKE" not in final_sql
    assert "LIMIT 500" in final_sql


# ---------------------------------------------------------------------------
# Tests: Value serialization
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_options_serializes_uuid_ids():
    """UUID primary keys are serialized to strings in the response."""
    fk_row = FakeRecord({
        "ref_schema": "files",
        "ref_table": "assets",
        "ref_column": "id",
    })
    col_rows = [
        FakeRecord({"column_name": "id", "data_type": "uuid"}),
        FakeRecord({"column_name": "original_name", "data_type": "text"}),
    ]
    uid = uuid.UUID("abcdef12-3456-7890-abcd-ef1234567890")
    options_rows = [
        FakeRecord({"id": uid, "label": "photo.jpg"}),
    ]

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="inventory",
            table="tool_files",
            column="asset_id",
            search=None,
            user={"id": 1},
        )

    assert result == [
        {"id": "abcdef12-3456-7890-abcd-ef1234567890", "label": "photo.jpg"}
    ]


# ---------------------------------------------------------------------------
# Tests: SQL safety
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_options_uses_quoted_identifiers():
    """All SQL identifiers are properly quoted to prevent injection."""
    fk_row = FakeRecord({
        "ref_schema": "my schema",
        "ref_table": "my table",
        "ref_column": "my_id",
    })
    col_rows = [
        FakeRecord({"column_name": "my_id", "data_type": "integer"}),
        FakeRecord({"column_name": "name", "data_type": "text"}),
    ]
    options_rows = []

    conn = MockConnection(call_results=[fk_row, col_rows, options_rows])
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_lookup_options(
            schema="inventory",
            table="tools",
            column="ref_id",
            search=None,
            user={"id": 1},
        )

    # Verify quoted identifiers in the final query
    final_sql = conn.calls[-1][0]
    assert '"my schema"' in final_sql
    assert '"my table"' in final_sql
    assert '"name"' in final_sql
    assert '"my_id"' in final_sql
