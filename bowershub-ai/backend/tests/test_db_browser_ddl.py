"""
Unit tests for DDL API endpoints in the DB Browser router.

Tests:
- POST /api/db/schemas — create schema
- POST /api/db/tables — create table with optional link table
- PATCH /api/db/tables/:schema/:table — rename, move schema, add/drop column
- POST /api/db/tables/:schema/:table/preview — SQL preview

Requirements: 14.6, 15.2, 15.3, 16.2, 16.3, 16.4, 16.5
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from backend.routers.db_browser import (
    _build_column_sql,
    _build_create_table_sql,
    _quote_ident,
    _validate_identifier,
)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


class MockRequest:
    """Simulates a FastAPI Request with a JSON body."""

    def __init__(self, body: dict[str, Any]):
        self._body = body

    async def json(self) -> dict[str, Any]:
        return self._body


class MockRecord(dict):
    """Simulates an asyncpg Record."""

    def __getattr__(self, key: str) -> Any:
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)


class MockConnection:
    """Simulates an asyncpg connection with programmable fetchval/fetch/execute."""

    def __init__(self):
        self.fetchval_results: list[Any] = []
        self.fetch_results: list[list[MockRecord]] = []
        self.executed_sql: list[str] = []
        self._fetchval_idx = 0
        self._fetch_idx = 0

    async def fetchval(self, query: str, *args) -> Any:
        idx = self._fetchval_idx
        self._fetchval_idx += 1
        if idx < len(self.fetchval_results):
            return self.fetchval_results[idx]
        return None

    async def fetch(self, query: str, *args) -> list[MockRecord]:
        idx = self._fetch_idx
        self._fetch_idx += 1
        if idx < len(self.fetch_results):
            return self.fetch_results[idx]
        return []

    async def execute(self, query: str, *args) -> str:
        self.executed_sql.append(query)
        return "CREATE TABLE"


class MockPoolCtx:
    def __init__(self, conn: MockConnection):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockPool:
    def __init__(self, conn: MockConnection):
        self._conn = conn

    def acquire(self):
        return MockPoolCtx(self._conn)


# ---------------------------------------------------------------------------
# Tests for _validate_identifier
# ---------------------------------------------------------------------------


class TestValidateIdentifier:
    def test_valid_names(self):
        _validate_identifier("tools", "test")
        _validate_identifier("router_bits", "test")
        _validate_identifier("_private", "test")
        _validate_identifier("a1b2c3", "test")

    def test_empty_name_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_identifier("", "Schema name")
        assert exc_info.value.status_code == 400

    def test_whitespace_only_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_identifier("   ", "Schema name")
        assert exc_info.value.status_code == 400

    def test_too_long_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_identifier("a" * 64, "Name")
        assert exc_info.value.status_code == 400

    def test_uppercase_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_identifier("MyTable", "Name")
        assert exc_info.value.status_code == 400

    def test_spaces_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_identifier("my table", "Name")
        assert exc_info.value.status_code == 400

    def test_starts_with_number_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_identifier("1table", "Name")
        assert exc_info.value.status_code == 400

    def test_special_chars_rejected(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_identifier("drop;--", "Name")
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Tests for _build_column_sql
# ---------------------------------------------------------------------------


class TestBuildColumnSql:
    def test_basic_text_column(self):
        result = _build_column_sql({"name": "brand", "type": "text", "nullable": True})
        assert result == '"brand" TEXT'

    def test_integer_not_null(self):
        result = _build_column_sql({"name": "quantity", "type": "integer", "nullable": False})
        assert result == '"quantity" INTEGER NOT NULL'

    def test_decimal_with_default(self):
        result = _build_column_sql(
            {"name": "price", "type": "decimal", "nullable": True, "default": "0.00"}
        )
        assert result == '"price" NUMERIC DEFAULT 0.00'

    def test_negative_numeric_default_passes_through(self):
        result = _build_column_sql(
            {"name": "balance", "type": "integer", "nullable": True, "default": "-5"}
        )
        assert result == '"balance" INTEGER DEFAULT -5'

    def test_keyword_default_now_is_allowed(self):
        result = _build_column_sql(
            {"name": "seen_at", "type": "timestamp", "nullable": True, "default": "now()"}
        )
        assert result == '"seen_at" TIMESTAMPTZ DEFAULT NOW()'

    def test_boolean_keyword_default_canonicalized(self):
        result = _build_column_sql(
            {"name": "active", "type": "boolean", "nullable": True, "default": "false"}
        )
        assert result == '"active" BOOLEAN DEFAULT FALSE'

    def test_plain_string_default_is_quoted(self):
        # An unquoted word default is emitted as a string literal, not a bare ident.
        result = _build_column_sql(
            {"name": "status", "type": "text", "nullable": True, "default": "pending"}
        )
        assert result == '"status" TEXT DEFAULT \'pending\''

    def test_quoted_string_default_preserved(self):
        result = _build_column_sql(
            {"name": "status", "type": "text", "nullable": True, "default": "'pending'"}
        )
        assert result == '"status" TEXT DEFAULT \'pending\''

    def test_default_injection_is_neutralized(self):
        # project-review.md C4: the DEFAULT clause was raw-interpolated. A crafted
        # value must become an inert string literal, never executable SQL.
        evil = "0); DROP TABLE public.bh_users; --"
        result = _build_column_sql(
            {"name": "qty", "type": "integer", "nullable": True, "default": evil}
        )
        # The entire payload is enclosed in one single-quoted literal — it cannot
        # terminate the DEFAULT clause and start a new statement.
        assert result == (
            '"qty" INTEGER DEFAULT \'0); DROP TABLE public.bh_users; --\''
        )
        default_frag = result.split("DEFAULT ", 1)[1]
        assert default_frag.startswith("'") and default_frag.endswith("'")

    def test_default_with_embedded_quote_is_escaped(self):
        result = _build_column_sql(
            {"name": "note", "type": "text", "nullable": True, "default": "it's fine"}
        )
        # Single quote doubled inside the literal — no early string termination.
        assert result == '"note" TEXT DEFAULT \'it\'\'s fine\''

    def test_default_fake_closing_quote_is_neutralized(self):
        # A value that opens but does not cleanly close a quoted literal must be
        # re-quoted as a whole, not trusted as-is.
        evil = "'); DROP TABLE x; --"
        result = _build_column_sql(
            {"name": "qty", "type": "integer", "nullable": True, "default": evil}
        )
        assert result == (
            '"qty" INTEGER DEFAULT \'\'\'); DROP TABLE x; --\''
        )

    def test_boolean_column(self):
        result = _build_column_sql({"name": "has_bearing", "type": "boolean", "nullable": True})
        assert result == '"has_bearing" BOOLEAN'

    def test_lookup_type_maps_to_integer(self):
        result = _build_column_sql({"name": "category_id", "type": "lookup", "nullable": True})
        assert result == '"category_id" INTEGER'

    def test_unknown_type_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _build_column_sql({"name": "col", "type": "blob", "nullable": True})
        assert exc_info.value.status_code == 400
        assert "Unknown column type" in exc_info.value.detail

    def test_empty_name_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _build_column_sql({"name": "", "type": "text", "nullable": True})
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Tests for _build_create_table_sql
# ---------------------------------------------------------------------------


class TestBuildCreateTableSql:
    def test_basic_table(self):
        sql = _build_create_table_sql(
            "inventory",
            "widgets",
            [{"name": "brand", "type": "text", "nullable": True}],
            include_image_support=False,
        )
        assert 'CREATE TABLE "inventory"."widgets"' in sql
        assert '"id" SERIAL PRIMARY KEY' in sql
        assert '"brand" TEXT' in sql
        assert '"created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()' in sql
        assert '"updated_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()' in sql

    def test_with_image_support(self):
        sql = _build_create_table_sql(
            "inventory",
            "tools",
            [{"name": "brand", "type": "text", "nullable": True}],
            include_image_support=True,
        )
        assert 'CREATE TABLE "inventory"."tools"' in sql
        assert 'CREATE TABLE "inventory"."tools_files"' in sql
        assert '"tool_id" INTEGER NOT NULL REFERENCES' in sql
        assert '"asset_id" UUID NOT NULL REFERENCES files.assets' in sql

    def test_with_lookup_fk(self):
        sql = _build_create_table_sql(
            "inventory",
            "items",
            [
                {"name": "brand", "type": "text", "nullable": True},
                {
                    "name": "category_id",
                    "type": "lookup",
                    "nullable": True,
                    "fk_schema": "public",
                    "fk_table": "categories",
                    "fk_column": "id",
                },
            ],
            include_image_support=False,
        )
        assert '"category_id" INTEGER' in sql
        assert 'CONSTRAINT "fk_items_category_id"' in sql
        assert 'REFERENCES "public"."categories"("id")' in sql

    def test_empty_columns_raises(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _build_create_table_sql("test", "t", [], include_image_support=False)
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Tests for POST /schemas (create_schema)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_schema_success():
    """Successfully creates a new schema."""
    from backend.routers.db_browser import create_schema

    conn = MockConnection()
    conn.fetchval_results = [False]  # schema does not exist
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"name": "woodshop"})
        result = await create_schema(request=request, user={"id": 1, "role": "admin"})

    assert result["ok"] is True
    assert result["schema"] == "woodshop"
    assert 'CREATE SCHEMA "woodshop"' in result["sql"]
    assert len(conn.executed_sql) == 1


@pytest.mark.asyncio
async def test_create_schema_conflict():
    """Returns 409 when schema already exists."""
    from fastapi import HTTPException

    from backend.routers.db_browser import create_schema

    conn = MockConnection()
    conn.fetchval_results = [True]  # schema already exists
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"name": "inventory"})
        with pytest.raises(HTTPException) as exc_info:
            await create_schema(request=request, user={"id": 1, "role": "admin"})
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_create_schema_invalid_name():
    """Returns 400 for invalid schema names."""
    from fastapi import HTTPException

    from backend.routers.db_browser import create_schema

    conn = MockConnection()
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"name": "DROP TABLE"})
        with pytest.raises(HTTPException) as exc_info:
            await create_schema(request=request, user={"id": 1, "role": "admin"})
        assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Tests for POST /tables (create_table)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_table_success():
    """Successfully creates a new table."""
    from backend.routers.db_browser import create_table

    conn = MockConnection()
    conn.fetchval_results = [True, False]  # schema exists, table does not exist
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest(
            {
                "schema": "inventory",
                "table": "gadgets",
                "columns": [
                    {"name": "brand", "type": "text", "nullable": True},
                    {"name": "price", "type": "decimal", "nullable": False, "default": "0"},
                ],
                "include_image_support": False,
            }
        )
        result = await create_table(request=request, user={"id": 1, "role": "admin"})

    assert result["ok"] is True
    assert result["schema"] == "inventory"
    assert result["table"] == "gadgets"
    assert "CREATE TABLE" in result["sql"]


@pytest.mark.asyncio
async def test_create_table_with_image_support():
    """Creates both main table and link table when image support is requested."""
    from backend.routers.db_browser import create_table

    conn = MockConnection()
    conn.fetchval_results = [True, False]  # schema exists, table does not exist
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest(
            {
                "schema": "inventory",
                "table": "tools",
                "columns": [{"name": "brand", "type": "text", "nullable": True}],
                "include_image_support": True,
            }
        )
        result = await create_table(request=request, user={"id": 1, "role": "admin"})

    assert result["ok"] is True
    assert "tools_files" in result["sql"]


@pytest.mark.asyncio
async def test_create_table_schema_not_exists():
    """Returns 400 when target schema doesn't exist."""
    from fastapi import HTTPException

    from backend.routers.db_browser import create_table

    conn = MockConnection()
    conn.fetchval_results = [False]  # schema does not exist
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest(
            {
                "schema": "nonexistent",
                "table": "stuff",
                "columns": [{"name": "x", "type": "text", "nullable": True}],
            }
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_table(request=request, user={"id": 1, "role": "admin"})
        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_create_table_already_exists():
    """Returns 409 when table already exists."""
    from fastapi import HTTPException

    from backend.routers.db_browser import create_table

    conn = MockConnection()
    conn.fetchval_results = [True, True]  # schema exists, table exists
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest(
            {
                "schema": "inventory",
                "table": "tools",
                "columns": [{"name": "brand", "type": "text", "nullable": True}],
            }
        )
        with pytest.raises(HTTPException) as exc_info:
            await create_table(request=request, user={"id": 1, "role": "admin"})
        assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Tests for POST /tables/:schema/:table/preview
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preview_returns_sql_without_executing():
    """Preview endpoint returns SQL without executing it."""
    from backend.routers.db_browser import preview_create_table

    request = MockRequest(
        {
            "columns": [
                {"name": "brand", "type": "text", "nullable": True},
                {"name": "weight", "type": "decimal", "nullable": False},
            ],
            "include_image_support": True,
        }
    )
    result = await preview_create_table(
        schema="inventory",
        table="widgets",
        request=request,
        user={"id": 1, "role": "admin"},
    )

    assert "sql" in result
    assert 'CREATE TABLE "inventory"."widgets"' in result["sql"]
    assert '"brand" TEXT' in result["sql"]
    assert '"weight" NUMERIC NOT NULL' in result["sql"]
    assert "widgets_files" in result["sql"]


# ---------------------------------------------------------------------------
# Tests for PATCH /tables/:schema/:table (alter_table)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alter_table_rename():
    """Rename action executes ALTER TABLE RENAME TO."""
    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True]  # table exists
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "rename", "new_name": "gadgets"})
        result = await alter_table(
            schema="inventory",
            table="widgets",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["ok"] is True
    assert result["action"] == "rename"
    assert result["new_name"] == "gadgets"
    assert "RENAME TO" in result["sql"]


@pytest.mark.asyncio
async def test_alter_table_move_schema():
    """Move schema action executes ALTER TABLE SET SCHEMA."""
    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True, True]  # table exists, target schema exists
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "move_schema", "new_schema": "public"})
        result = await alter_table(
            schema="inventory",
            table="tools",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["ok"] is True
    assert result["action"] == "move_schema"
    assert result["new_schema"] == "public"
    assert "SET SCHEMA" in result["sql"]


@pytest.mark.asyncio
async def test_alter_table_move_schema_target_not_exists():
    """Returns 400 when target schema doesn't exist."""
    from fastapi import HTTPException

    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True, False]  # table exists, target schema does NOT exist
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "move_schema", "new_schema": "nonexistent"})
        with pytest.raises(HTTPException) as exc_info:
            await alter_table(
                schema="inventory",
                table="tools",
                request=request,
                user={"id": 1, "role": "admin"},
            )
        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_alter_table_add_column():
    """Add column action executes ALTER TABLE ADD COLUMN."""
    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True]  # table exists
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest(
            {"action": "add_column", "name": "weight_kg", "type": "decimal", "nullable": True}
        )
        result = await alter_table(
            schema="inventory",
            table="tools",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["ok"] is True
    assert result["action"] == "add_column"
    assert result["column"] == "weight_kg"
    assert "ADD COLUMN" in result["sql"]
    assert "NUMERIC" in result["sql"]


@pytest.mark.asyncio
async def test_alter_table_add_lookup_column():
    """Add lookup column creates the column + FK constraint."""
    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True]  # table exists
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest(
            {
                "action": "add_column",
                "name": "category_id",
                "type": "lookup",
                "nullable": True,
                "fk_schema": "public",
                "fk_table": "categories",
                "fk_column": "id",
            }
        )
        result = await alter_table(
            schema="inventory",
            table="tools",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["ok"] is True
    assert "ADD COLUMN" in result["sql"]
    assert "ADD CONSTRAINT" in result["sql"]
    assert "FOREIGN KEY" in result["sql"]
    # Both statements were executed
    assert len(conn.executed_sql) == 2


@pytest.mark.asyncio
async def test_alter_table_drop_column():
    """Drop column action executes ALTER TABLE DROP COLUMN."""
    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True, True]  # table exists, column exists
    conn.fetch_results = [[]]  # no PK columns (or PK doesn't include the target column)
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "drop_column", "column_name": "old_field"})
        result = await alter_table(
            schema="inventory",
            table="tools",
            request=request,
            user={"id": 1, "role": "admin"},
        )

    assert result["ok"] is True
    assert result["action"] == "drop_column"
    assert result["column"] == "old_field"
    assert "DROP COLUMN" in result["sql"]


@pytest.mark.asyncio
async def test_alter_table_drop_pk_column_rejected():
    """Cannot drop a primary key column."""
    from fastapi import HTTPException

    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True]  # table exists
    conn.fetch_results = [[MockRecord({"column_name": "id"})]]  # "id" is the PK
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "drop_column", "column_name": "id"})
        with pytest.raises(HTTPException) as exc_info:
            await alter_table(
                schema="inventory",
                table="tools",
                request=request,
                user={"id": 1, "role": "admin"},
            )
        assert exc_info.value.status_code == 400
        assert "primary key" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_alter_table_drop_nonexistent_column():
    """Returns 404 when trying to drop a column that doesn't exist."""
    from fastapi import HTTPException

    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True, False]  # table exists, column does NOT exist
    conn.fetch_results = [[]]  # no PK match
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "drop_column", "column_name": "ghost_col"})
        with pytest.raises(HTTPException) as exc_info:
            await alter_table(
                schema="inventory",
                table="tools",
                request=request,
                user={"id": 1, "role": "admin"},
            )
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_alter_table_unknown_action():
    """Returns 400 for unknown action."""
    from fastapi import HTTPException

    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [True]  # table exists
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "explode"})
        with pytest.raises(HTTPException) as exc_info:
            await alter_table(
                schema="inventory",
                table="tools",
                request=request,
                user={"id": 1, "role": "admin"},
            )
        assert exc_info.value.status_code == 400
        assert "Unknown action" in exc_info.value.detail


@pytest.mark.asyncio
async def test_alter_table_not_found():
    """Returns 404 when table doesn't exist."""
    from fastapi import HTTPException

    from backend.routers.db_browser import alter_table

    conn = MockConnection()
    conn.fetchval_results = [False]  # table does NOT exist
    pool = MockPool(conn)

    with patch("backend.routers.db_browser.get_pool", return_value=pool):
        request = MockRequest({"action": "rename", "new_name": "new_name"})
        with pytest.raises(HTTPException) as exc_info:
            await alter_table(
                schema="inventory",
                table="nonexistent",
                request=request,
                user={"id": 1, "role": "admin"},
            )
        assert exc_info.value.status_code == 404
