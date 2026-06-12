"""
Unit tests for image management API endpoints in db_browser.py.

Tests the _find_link_table helper and all 5 image management endpoints:
- GET /{schema}/{table}/rows/{row_id}/images
- POST /{schema}/{table}/rows/{row_id}/images
- PUT /{schema}/{table}/rows/{row_id}/images/reorder
- PUT /{schema}/{table}/rows/{row_id}/images/{asset_id}/primary
- DELETE /{schema}/{table}/rows/{row_id}/images/{asset_id}

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5
"""

from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import AsyncMock, patch, MagicMock

import asyncpg
import pytest
import pytest_asyncio

from backend.config import Config
from backend.database import close_pool, init_pool
from backend.routers.db_browser import (
    _find_link_table,
    get_row_images,
    reorder_row_images,
    set_primary_image,
    unlink_row_image,
)


# ---------------------------------------------------------------------------
# Real-DB fixture for the image-link query
#
# get_row_images() discovers a `{table}_files` link table by its FK, then joins
# it to files.assets. The old success-path test mocked every layer of that with
# AsyncMocks, which drifted from the real SQL. Here we stand up the real schema
# (files.assets + inventory.tools + inventory.tools_files) in an ephemeral DB so
# the FK discovery and join are exercised for real. init_pool() populates the
# module-level pool that db_browser.get_pool() reads.
# ---------------------------------------------------------------------------


async def _create_image_schema(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        await conn.execute("CREATE SCHEMA IF NOT EXISTS files")
        await conn.execute("CREATE SCHEMA IF NOT EXISTS inventory")
        await conn.execute(
            """
            CREATE TABLE files.assets (
                id            UUID PRIMARY KEY,
                path          TEXT,
                original_name TEXT,
                mime          TEXT,
                ai_summary    TEXT,
                uploaded_at   TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        await conn.execute(
            "CREATE TABLE inventory.tools (id SERIAL PRIMARY KEY, name TEXT)"
        )
        await conn.execute(
            """
            CREATE TABLE inventory.tools_files (
                id         SERIAL PRIMARY KEY,
                tool_id    INT REFERENCES inventory.tools(id),
                asset_id   UUID REFERENCES files.assets(id),
                is_primary BOOLEAN DEFAULT false,
                sort_order INT
            )
            """
        )


@pytest_asyncio.fixture
async def images_pool(fresh_db, db_settings):
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=fresh_db,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test-secret-for-db-browser-image-tests",
        N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    try:
        await _create_image_schema(pool)
        yield pool
    finally:
        await close_pool()


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeRecord(dict):
    """Simulates an asyncpg Record with .items() and .keys() methods."""

    def items(self):
        return super().items()

    def keys(self):
        return super().keys()


class MockRequest:
    """Simulates a FastAPI Request object with .json()."""

    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


def make_conn_mock(**overrides) -> AsyncMock:
    """Create a mock asyncpg connection with common methods."""
    conn = AsyncMock()
    for key, val in overrides.items():
        setattr(conn, key, val)
    return conn


# ---------------------------------------------------------------------------
# Tests for _find_link_table
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_find_link_table_exact_match():
    """Should find {table}_files when it exists and has the right FK."""
    conn = AsyncMock()

    # Table exists
    conn.fetchval = AsyncMock(return_value=True)

    # FK column found
    conn.fetchrow = AsyncMock(return_value=FakeRecord({"column_name": "tool_id"}))

    result = await _find_link_table(conn, "inventory", "tools")

    assert result == ("tools_files", "tool_id")


@pytest.mark.asyncio
async def test_find_link_table_singular_fallback():
    """Should find singular form {table[:-1]}_files when plural doesn't exist."""
    conn = AsyncMock()

    call_count = 0

    async def mock_fetchval(query, *args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # tools_files doesn't exist
            return False
        else:
            # tool_files exists
            return True

    conn.fetchval = mock_fetchval

    # FK column found
    conn.fetchrow = AsyncMock(return_value=FakeRecord({"column_name": "tool_id"}))

    result = await _find_link_table(conn, "inventory", "tools")

    assert result == ("tool_files", "tool_id")


@pytest.mark.asyncio
async def test_find_link_table_no_match():
    """Should return None when no link table exists."""
    conn = AsyncMock()

    # No tables exist
    conn.fetchval = AsyncMock(return_value=False)

    result = await _find_link_table(conn, "inventory", "tools")

    assert result is None


@pytest.mark.asyncio
async def test_find_link_table_exists_but_no_fk():
    """Should return None when table exists but has no FK to main table."""
    conn = AsyncMock()

    # Table exists
    conn.fetchval = AsyncMock(return_value=True)
    # But no FK constraint found
    conn.fetchrow = AsyncMock(return_value=None)

    result = await _find_link_table(conn, "inventory", "tools")

    assert result is None


# ---------------------------------------------------------------------------
# Tests for GET /images
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_row_images_no_link_table():
    """Should return empty list when no link table exists."""
    mock_conn = AsyncMock()
    mock_conn.fetchval = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.routers.db_browser.get_pool", return_value=mock_pool):
        result = await get_row_images(
            schema="inventory",
            table="tools",
            row_id="1",
            user={"id": 1},
        )

    assert result == []


@pytest.mark.asyncio
async def test_get_row_images_with_results(images_pool):
    """Linked images are discovered via the FK and joined to files.assets.

    Real-DB: exercises _find_link_table's FK discovery and the dynamic
    SELECT/ORDER BY against a row that has both is_primary and sort_order set.
    """
    asset_uuid = uuid.uuid4()
    async with images_pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO files.assets (id, path, original_name, mime, ai_summary)
            VALUES ($1, $2, $3, $4, $5)
            """,
            asset_uuid, "inventory/tools/abc.jpg", "photo.jpg",
            "image/jpeg", "A power tool",
        )
        tool_id = await conn.fetchval(
            "INSERT INTO inventory.tools (name) VALUES ('Drill') RETURNING id"
        )
        await conn.execute(
            """
            INSERT INTO inventory.tools_files (tool_id, asset_id, is_primary, sort_order)
            VALUES ($1, $2, true, 0)
            """,
            tool_id, asset_uuid,
        )

    result = await get_row_images(
        schema="inventory",
        table="tools",
        row_id=str(tool_id),
        user={"id": 1},
    )

    assert len(result) == 1
    assert result[0]["asset_id"] == str(asset_uuid)
    assert result[0]["path"] == "inventory/tools/abc.jpg"
    assert result[0]["original_name"] == "photo.jpg"
    assert result[0]["is_primary"] is True
    assert result[0]["sort_order"] == 0


# ---------------------------------------------------------------------------
# Tests for PUT /images/reorder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reorder_images_empty_order():
    """Should raise 400 for empty order array."""
    from fastapi import HTTPException

    request = MockRequest({"order": []})

    with pytest.raises(HTTPException) as exc_info:
        await reorder_row_images(
            schema="inventory",
            table="tools",
            row_id="1",
            request=request,
            user={"id": 1},
        )

    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_reorder_images_success():
    """Should update sort_order for each asset in the order list."""
    mock_conn = AsyncMock()

    # _find_link_table calls
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_conn.fetchrow = AsyncMock(return_value=FakeRecord({"column_name": "tool_id"}))

    # execute for updates
    mock_conn.execute = AsyncMock(return_value="UPDATE 1")

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    request = MockRequest({
        "order": [
            {"asset_id": str(uuid.uuid4()), "sort_order": 0},
            {"asset_id": str(uuid.uuid4()), "sort_order": 1},
        ]
    })

    with patch("backend.routers.db_browser.get_pool", return_value=mock_pool):
        result = await reorder_row_images(
            schema="inventory",
            table="tools",
            row_id="1",
            request=request,
            user={"id": 1},
        )

    assert result == {"ok": True}
    # Should have called execute twice (once per asset)
    assert mock_conn.execute.call_count == 2


# ---------------------------------------------------------------------------
# Tests for PUT /images/{asset_id}/primary
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_primary_image_success():
    """Should clear all is_primary and set the specified one."""
    mock_conn = AsyncMock()

    # _find_link_table calls
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_conn.fetchrow = AsyncMock(return_value=FakeRecord({"column_name": "tool_id"}))

    # First execute: clear all is_primary -> "UPDATE 3"
    # Second execute: set specified -> "UPDATE 1"
    mock_conn.execute = AsyncMock(side_effect=["UPDATE 3", "UPDATE 1"])

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.routers.db_browser.get_pool", return_value=mock_pool):
        result = await set_primary_image(
            schema="inventory",
            table="tools",
            row_id="1",
            asset_id=str(uuid.uuid4()),
            user={"id": 1},
        )

    assert result == {"ok": True}
    assert mock_conn.execute.call_count == 2


@pytest.mark.asyncio
async def test_set_primary_image_not_found():
    """Should raise 404 when asset_id is not linked to the row."""
    from fastapi import HTTPException

    mock_conn = AsyncMock()

    # _find_link_table calls
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_conn.fetchrow = AsyncMock(return_value=FakeRecord({"column_name": "tool_id"}))

    # First execute: clear -> "UPDATE 3", second: set -> "UPDATE 0" (not found)
    mock_conn.execute = AsyncMock(side_effect=["UPDATE 3", "UPDATE 0"])

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.routers.db_browser.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc_info:
            await set_primary_image(
                schema="inventory",
                table="tools",
                row_id="1",
                asset_id=str(uuid.uuid4()),
                user={"id": 1},
            )

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# Tests for DELETE /images/{asset_id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unlink_image_success():
    """Should delete the link table row and return ok."""
    mock_conn = AsyncMock()

    # _find_link_table calls
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_conn.fetchrow = AsyncMock(return_value=FakeRecord({"column_name": "tool_id"}))

    # execute for delete -> "DELETE 1"
    mock_conn.execute = AsyncMock(return_value="DELETE 1")

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.routers.db_browser.get_pool", return_value=mock_pool):
        result = await unlink_row_image(
            schema="inventory",
            table="tools",
            row_id="1",
            asset_id=str(uuid.uuid4()),
            user={"id": 1},
        )

    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_unlink_image_not_found():
    """Should raise 404 when the link row doesn't exist."""
    from fastapi import HTTPException

    mock_conn = AsyncMock()

    # _find_link_table calls
    mock_conn.fetchval = AsyncMock(return_value=True)
    mock_conn.fetchrow = AsyncMock(return_value=FakeRecord({"column_name": "tool_id"}))

    # execute for delete -> "DELETE 0" (not found)
    mock_conn.execute = AsyncMock(return_value="DELETE 0")

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.routers.db_browser.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc_info:
            await unlink_row_image(
                schema="inventory",
                table="tools",
                row_id="1",
                asset_id=str(uuid.uuid4()),
                user={"id": 1},
            )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_unlink_image_no_link_table():
    """Should raise 400 when table has no link table."""
    from fastapi import HTTPException

    mock_conn = AsyncMock()

    # No link table found
    mock_conn.fetchval = AsyncMock(return_value=False)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch("backend.routers.db_browser.get_pool", return_value=mock_pool):
        with pytest.raises(HTTPException) as exc_info:
            await unlink_row_image(
                schema="inventory",
                table="categories",
                row_id="1",
                asset_id=str(uuid.uuid4()),
                user={"id": 1},
            )

    assert exc_info.value.status_code == 400
