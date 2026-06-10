"""
Unit tests for GET /api/db/schemas endpoint.

Tests the schema introspection logic: filtering system schemas, parallel queries,
link-table detection, and response format.

Requirements: 2.1, 2.3, 2.4
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio


# ---------------------------------------------------------------------------
# Mock infrastructure (simulates asyncpg pool/connection behavior)
# ---------------------------------------------------------------------------


class MockRecord(dict):
    """Simulates an asyncpg Record with both dict-like and attribute access."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


def make_records(rows: list[dict[str, Any]]) -> list[MockRecord]:
    """Convert plain dicts to MockRecord instances."""
    return [MockRecord(r) for r in rows]


class MockConnection:
    """Simulates an asyncpg connection returning preconfigured results."""

    def __init__(self, results: dict[str, list[dict[str, Any]]]):
        self._results = results
        self._call_count = 0

    async def fetch(self, query: str, *args) -> list[MockRecord]:
        self._call_count += 1
        # Match query by a key substring
        for key, rows in self._results.items():
            if key in query:
                return make_records(rows)
        return []


class MockPoolCtx:
    def __init__(self, conn: MockConnection):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockPool:
    def __init__(self, results: dict[str, list[dict[str, Any]]]):
        self._conn = MockConnection(results)

    def acquire(self):
        return MockPoolCtx(self._conn)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_schemas_returns_correct_structure():
    """Schemas endpoint returns proper schema/table hierarchy."""
    from backend.routers.db_browser import get_schemas

    mock_results = {
        "information_schema.schemata": [
            {"schema_name": "inventory"},
            {"schema_name": "public"},
        ],
        "information_schema.tables": [
            {"table_schema": "inventory", "table_name": "tools"},
            {"table_schema": "inventory", "table_name": "tool_files"},
            {"table_schema": "inventory", "table_name": "router_bits"},
            {"table_schema": "inventory", "table_name": "router_bit_files"},
            {"table_schema": "public", "table_name": "transactions"},
            {"table_schema": "public", "table_name": "accounts"},
        ],
        "information_schema.columns": [
            {"table_schema": "inventory", "table_name": "tools", "col_count": 15},
            {"table_schema": "inventory", "table_name": "tool_files", "col_count": 3},
            {"table_schema": "inventory", "table_name": "router_bits", "col_count": 12},
            {"table_schema": "inventory", "table_name": "router_bit_files", "col_count": 3},
            {"table_schema": "public", "table_name": "transactions", "col_count": 20},
            {"table_schema": "public", "table_name": "accounts", "col_count": 8},
        ],
        "pg_stat_user_tables": [
            {"schemaname": "inventory", "relname": "tools", "n_live_tup": 14},
            {"schemaname": "inventory", "relname": "tool_files", "n_live_tup": 28},
            {"schemaname": "inventory", "relname": "router_bits", "n_live_tup": 73},
            {"schemaname": "inventory", "relname": "router_bit_files", "n_live_tup": 72},
            {"schemaname": "public", "relname": "transactions", "n_live_tup": 500},
            {"schemaname": "public", "relname": "accounts", "n_live_tup": 17},
        ],
    }

    pool = MockPool(mock_results)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_schemas(user={"id": 1, "role": "admin"})

    assert isinstance(result, list)
    assert len(result) == 2

    # Schemas are sorted alphabetically
    assert result[0]["name"] == "inventory"
    assert result[1]["name"] == "public"

    # Inventory schema: tools and router_bits visible, _files tables excluded
    inv_tables = result[0]["tables"]
    inv_names = [t["name"] for t in inv_tables]
    assert "tools" in inv_names
    assert "router_bits" in inv_names
    assert "tool_files" not in inv_names
    assert "router_bit_files" not in inv_names

    # Link table detection
    tools_entry = next(t for t in inv_tables if t["name"] == "tools")
    assert tools_entry["has_link_table"] is True
    assert tools_entry["column_count"] == 15
    assert tools_entry["row_count"] == 14

    router_bits_entry = next(t for t in inv_tables if t["name"] == "router_bits")
    assert router_bits_entry["has_link_table"] is True
    assert router_bits_entry["column_count"] == 12
    assert router_bits_entry["row_count"] == 73

    # Public schema: transactions and accounts, no link tables
    pub_tables = result[1]["tables"]
    pub_names = [t["name"] for t in pub_tables]
    assert "transactions" in pub_names
    assert "accounts" in pub_names

    transactions_entry = next(t for t in pub_tables if t["name"] == "transactions")
    assert transactions_entry["has_link_table"] is False
    assert transactions_entry["column_count"] == 20
    assert transactions_entry["row_count"] == 500


@pytest.mark.asyncio
async def test_schemas_excludes_system_schemas():
    """System schemas (pg_*, information_schema) are never in the response."""
    from backend.routers.db_browser import get_schemas

    # Only user schemas returned from information_schema query
    mock_results = {
        "information_schema.schemata": [
            {"schema_name": "public"},
        ],
        "information_schema.tables": [
            {"table_schema": "public", "table_name": "test_table"},
        ],
        "information_schema.columns": [
            {"table_schema": "public", "table_name": "test_table", "col_count": 5},
        ],
        "pg_stat_user_tables": [
            {"schemaname": "public", "relname": "test_table", "n_live_tup": 10},
        ],
    }

    pool = MockPool(mock_results)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_schemas(user={"id": 1, "role": "admin"})

    schema_names = [s["name"] for s in result]
    assert "pg_catalog" not in schema_names
    assert "pg_toast" not in schema_names
    assert "information_schema" not in schema_names
    assert "public" in schema_names


@pytest.mark.asyncio
async def test_schemas_empty_database():
    """Returns empty list when no user schemas exist."""
    from backend.routers.db_browser import get_schemas

    mock_results = {
        "information_schema.schemata": [],
        "information_schema.tables": [],
        "information_schema.columns": [],
        "pg_stat_user_tables": [],
    }

    pool = MockPool(mock_results)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_schemas(user={"id": 1, "role": "admin"})

    assert result == []


@pytest.mark.asyncio
async def test_schemas_schema_with_no_tables():
    """Schema with no tables still appears in the response with empty tables list."""
    from backend.routers.db_browser import get_schemas

    mock_results = {
        "information_schema.schemata": [
            {"schema_name": "empty_schema"},
            {"schema_name": "public"},
        ],
        "information_schema.tables": [
            {"table_schema": "public", "table_name": "users"},
        ],
        "information_schema.columns": [
            {"table_schema": "public", "table_name": "users", "col_count": 4},
        ],
        "pg_stat_user_tables": [
            {"schemaname": "public", "relname": "users", "n_live_tup": 2},
        ],
    }

    pool = MockPool(mock_results)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_schemas(user={"id": 1, "role": "admin"})

    assert len(result) == 2
    empty = next(s for s in result if s["name"] == "empty_schema")
    assert empty["tables"] == []


@pytest.mark.asyncio
async def test_schemas_tables_sorted_alphabetically():
    """Tables within each schema are sorted alphabetically."""
    from backend.routers.db_browser import get_schemas

    mock_results = {
        "information_schema.schemata": [
            {"schema_name": "inventory"},
        ],
        "information_schema.tables": [
            {"table_schema": "inventory", "table_name": "wood"},
            {"table_schema": "inventory", "table_name": "albums"},
            {"table_schema": "inventory", "table_name": "tools"},
            {"table_schema": "inventory", "table_name": "manuals"},
        ],
        "information_schema.columns": [
            {"table_schema": "inventory", "table_name": "wood", "col_count": 5},
            {"table_schema": "inventory", "table_name": "albums", "col_count": 6},
            {"table_schema": "inventory", "table_name": "tools", "col_count": 15},
            {"table_schema": "inventory", "table_name": "manuals", "col_count": 4},
        ],
        "pg_stat_user_tables": [
            {"schemaname": "inventory", "relname": "wood", "n_live_tup": 0},
            {"schemaname": "inventory", "relname": "albums", "n_live_tup": 0},
            {"schemaname": "inventory", "relname": "tools", "n_live_tup": 14},
            {"schemaname": "inventory", "relname": "manuals", "n_live_tup": 3},
        ],
    }

    pool = MockPool(mock_results)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_schemas(user={"id": 1, "role": "admin"})

    table_names = [t["name"] for t in result[0]["tables"]]
    assert table_names == sorted(table_names)
    assert table_names == ["albums", "manuals", "tools", "wood"]


@pytest.mark.asyncio
async def test_schemas_only_files_tables_in_schema():
    """Schema containing only _files tables still appears with empty tables list."""
    from backend.routers.db_browser import get_schemas

    mock_results = {
        "information_schema.schemata": [
            {"schema_name": "orphaned"},
        ],
        "information_schema.tables": [
            {"table_schema": "orphaned", "table_name": "legacy_files"},
        ],
        "information_schema.columns": [
            {"table_schema": "orphaned", "table_name": "legacy_files", "col_count": 3},
        ],
        "pg_stat_user_tables": [
            {"schemaname": "orphaned", "relname": "legacy_files", "n_live_tup": 5},
        ],
    }

    pool = MockPool(mock_results)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_schemas(user={"id": 1, "role": "admin"})

    assert len(result) == 1
    # "legacy_files" ends with "_files" so it's treated as a link table
    assert result[0]["tables"] == []


@pytest.mark.asyncio
async def test_schemas_link_table_detection_exact_match():
    """Link table detection uses exact '{table}_files' naming convention."""
    from backend.routers.db_browser import get_schemas

    mock_results = {
        "information_schema.schemata": [
            {"schema_name": "test"},
        ],
        "information_schema.tables": [
            {"table_schema": "test", "table_name": "documents"},
            {"table_schema": "test", "table_name": "documents_files"},
            {"table_schema": "test", "table_name": "old_files"},  # NOT a link table for 'old'
        ],
        "information_schema.columns": [
            {"table_schema": "test", "table_name": "documents", "col_count": 8},
            {"table_schema": "test", "table_name": "documents_files", "col_count": 3},
            {"table_schema": "test", "table_name": "old_files", "col_count": 3},
        ],
        "pg_stat_user_tables": [
            {"schemaname": "test", "relname": "documents", "n_live_tup": 50},
            {"schemaname": "test", "relname": "documents_files", "n_live_tup": 20},
            {"schemaname": "test", "relname": "old_files", "n_live_tup": 10},
        ],
    }

    pool = MockPool(mock_results)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        result = await get_schemas(user={"id": 1, "role": "admin"})

    # Only "documents" should be in main tables (both _files tables are excluded)
    tables = result[0]["tables"]
    table_names = [t["name"] for t in tables]
    assert "documents" in table_names
    assert "documents_files" not in table_names
    assert "old_files" not in table_names

    # documents has a link table (documents_files exists)
    docs = next(t for t in tables if t["name"] == "documents")
    assert docs["has_link_table"] is True
