"""
Database Browser API routes: schema introspection, CRUD, image management,
layout persistence, field hints, inbox processing, and schema management.

All endpoints are prefixed with /api/db and require ADMIN (require_admin) — the
DB browser exposes full-table read/export/DDL/CRUD with no per-table allowlist
(C4 declined), so it is admin-only end-to-end, reads included. A non-admin must
never reach it (e.g. GET /{schema}/{table}/export-csv on public.bh_users).

Requirements: 21.1, 21.2, 21.4
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import io
import json
import logging
import math
import os
import re
import shutil
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import httpx

import asyncpg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from starlette.responses import StreamingResponse
from fastapi.responses import FileResponse

from backend.database import get_pool
from backend.middleware.auth import require_admin
from backend.middleware.audit import AuditLogger
from backend.http_client import get_http_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/db", tags=["db-browser"])

# Schemas to exclude from introspection results
_EXCLUDED_SCHEMAS = frozenset([
    "pg_catalog",
    "pg_toast",
    "information_schema",
])

# Prefix patterns to exclude (pg_temp_*, pg_toast_temp_*, etc.)
_EXCLUDED_PREFIXES = ("pg_",)


# ---- Health / Ping -----------------------------------------------------------


@router.get("/ping")
async def ping(user: dict = Depends(require_admin)) -> dict[str, Any]:
    """
    Health check for the DB browser router.
    Verifies pool connectivity and returns basic status.
    """
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            result = await conn.fetchval("SELECT 1")
        return {"ok": True, "db": result == 1}
    except Exception as e:
        logger.error(f"DB browser ping failed: {e}")
        return {"ok": False, "db": False, "error": str(e)}


# ---- Schema Introspection ----------------------------------------------------


@router.get("/schemas")
async def get_schemas(user: dict = Depends(require_admin)) -> list[dict[str, Any]]:
    """
    Return all user-accessible schemas with their tables, column counts,
    approximate row counts, and link-table presence indicators.

    Runs queries in parallel for performance.
    Requirements: 2.1, 2.3, 2.4
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # 1. Get all user schemas (exclude system schemas)
        schema_rows = await conn.fetch("""
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'pg_toast', 'information_schema')
              AND schema_name NOT LIKE 'pg_%'
            ORDER BY schema_name
        """)

        schema_names = [row["schema_name"] for row in schema_rows]

        if not schema_names:
            return []

        # 2. Get all tables, column counts, and row counts.
        # Note: asyncpg does NOT support concurrent queries on the same connection,
        # so these must run sequentially (not via asyncio.gather).
        tables_rows = await conn.fetch("""
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema = ANY($1)
              AND table_type = 'BASE TABLE'
            ORDER BY table_schema, table_name
        """, schema_names)

        columns_rows = await conn.fetch("""
            SELECT table_schema, table_name, COUNT(*) as col_count
            FROM information_schema.columns
            WHERE table_schema = ANY($1)
            GROUP BY table_schema, table_name
        """, schema_names)

        # Approximate row counts from pg_stat_user_tables (fast, not exact)
        row_count_rows = await conn.fetch("""
            SELECT schemaname, relname, n_live_tup
            FROM pg_stat_user_tables
            WHERE schemaname = ANY($1)
        """, schema_names)

    # 3. Build lookup maps
    # Column counts: (schema, table) -> count
    col_counts: dict[tuple[str, str], int] = {}
    for row in columns_rows:
        col_counts[(row["table_schema"], row["table_name"])] = row["col_count"]

    # Row counts: (schema, table) -> approximate count
    row_counts: dict[tuple[str, str], int] = {}
    for row in row_count_rows:
        row_counts[(row["schemaname"], row["relname"])] = row["n_live_tup"]

    # All tables per schema (full set, including _files tables)
    all_tables_by_schema: dict[str, set[str]] = {}
    for row in tables_rows:
        schema = row["table_schema"]
        table = row["table_name"]
        all_tables_by_schema.setdefault(schema, set()).add(table)

    # 4. Build the response
    result: list[dict[str, Any]] = []

    for schema_name in schema_names:
        tables_in_schema = all_tables_by_schema.get(schema_name, set())

        # Identify link tables (tables ending with _files)
        link_tables = {t for t in tables_in_schema if t.endswith("_files")}

        # Main tables are everything that isn't a link table
        main_tables = sorted(tables_in_schema - link_tables)

        if not main_tables:
            # Still include the schema even if empty (user might want to create tables)
            result.append({"name": schema_name, "tables": []})
            continue

        table_list: list[dict[str, Any]] = []
        for table_name in main_tables:
            # Check if a corresponding _files link table exists.
            # Convention: link table = singular(table_name) + "_files"
            # e.g., tools → tool_files, router_bits → router_bit_files
            has_link_table = _has_link_table(table_name, tables_in_schema)

            table_list.append({
                "name": table_name,
                "column_count": col_counts.get((schema_name, table_name), 0),
                "row_count": row_counts.get((schema_name, table_name), 0),
                "has_link_table": has_link_table,
            })

        result.append({
            "name": schema_name,
            "tables": table_list,
        })

    return result


def _has_link_table(table_name: str, all_tables: set[str]) -> bool:
    """
    Check if a link table exists for the given table name.

    The naming convention is: singular(table_name) + "_files"
    Examples: tools → tool_files, router_bits → router_bit_files, wood → wood_files
    """
    # Try exact match first: table_name + "_files"
    if f"{table_name}_files" in all_tables:
        return True

    # Try singular form: strip trailing 's' (covers tools→tool, albums→album, etc.)
    if table_name.endswith("s"):
        singular = table_name[:-1]
        if f"{singular}_files" in all_tables:
            return True

    return False


# ---- Column Metadata ---------------------------------------------------------


@router.get("/{schema}/{table}/columns")
async def get_columns(
    schema: str,
    table: str,
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    Return column metadata for a table including name, type, nullable,
    default, primary key membership, and FK relationship info.

    Requirements: 3.1, 7.4
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Get primary key columns for this table
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            """,
            schema,
            table,
        )
        pk_columns = {row["column_name"] for row in pk_rows}

        # Get columns with FK info via left join on foreign key constraints
        col_rows = await conn.fetch(
            """
            SELECT
                c.column_name,
                c.data_type,
                c.is_nullable,
                c.column_default,
                ccu.table_schema AS fk_schema,
                ccu.table_name AS fk_table,
                ccu.column_name AS fk_column
            FROM information_schema.columns c
            LEFT JOIN information_schema.key_column_usage kcu
                ON kcu.table_schema = c.table_schema
                AND kcu.table_name = c.table_name
                AND kcu.column_name = c.column_name
            LEFT JOIN information_schema.table_constraints tc
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
                AND tc.constraint_type = 'FOREIGN KEY'
            LEFT JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.constraint_schema = tc.constraint_schema
            WHERE c.table_schema = $1
                AND c.table_name = $2
            ORDER BY c.ordinal_position
            """,
            schema,
            table,
        )

        columns = []
        for row in col_rows:
            columns.append(
                {
                    "column_name": row["column_name"],
                    "data_type": row["data_type"],
                    "is_nullable": row["is_nullable"],
                    "column_default": row["column_default"],
                    "is_pk": row["column_name"] in pk_columns,
                    "fk_schema": row["fk_schema"],
                    "fk_table": row["fk_table"],
                    "fk_column": row["fk_column"],
                }
            )

        return columns


# ---- Primary Key -------------------------------------------------------------


@router.get("/{schema}/{table}/pk")
async def get_primary_key(
    schema: str,
    table: str,
    user: dict = Depends(require_admin),
) -> dict[str, list[str]]:
    """
    Return the primary key column(s) for a table.

    Requirements: 3.1, 7.4
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema,
            table,
        )
        return {"pk_columns": [row["column_name"] for row in rows]}


# ---- Single Row Fetch --------------------------------------------------------


@router.get("/{schema}/{table}/rows/{row_id}")
async def get_row(
    schema: str,
    table: str,
    row_id: str,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Fetch a single row by its primary key value.

    Looks up the PK column(s) for the table, then queries for the row.
    Returns 404 if the row is not found.

    Requirements: 7.1
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # 1. Determine the primary key column(s)
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema,
            table,
        )

        if not pk_rows:
            raise HTTPException(
                status_code=404,
                detail=f"Table {schema}.{table} not found or has no primary key",
            )

        # For single-column PKs (the common case), use the first PK column
        pk_column = pk_rows[0]["column_name"]

        # 2. Fetch the row using properly quoted identifiers
        query = (
            f'SELECT * FROM "{schema}"."{table}" '
            f'WHERE "{pk_column}" = $1'
        )

        # asyncpg will cast the parameter; try the raw string value first
        # Most PKs are integer or UUID — attempt int cast, fall back to string
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        row = await conn.fetchrow(query, pk_value)

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Row with {pk_column}={row_id} not found in {schema}.{table}",
            )

        # 3. Convert asyncpg Record to dict (handles UUID, datetime, Decimal via
        #    FastAPI's default JSON encoder)
        return dict(row)


# ---- Paginated Rows ----------------------------------------------------------


def _quote_ident(name: str) -> str:
    """
    Quote a SQL identifier (schema, table, column name) to prevent injection.
    Doubles any embedded double-quotes per SQL standard quoting rules.
    """
    return '"' + name.replace('"', '""') + '"'


@router.get("/{schema}/{table}/rows")
async def get_rows(
    schema: str,
    table: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50),
    sort_column: Optional[str] = Query(default=None),
    sort_direction: Optional[str] = Query(default=None),
    filters: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Return paginated rows from a table with server-side sorting, filtering,
    and cross-column text search.

    Query params:
      - page: 1-based page number (default 1)
      - page_size: rows per page (allowed: 25, 50, 100; default 50)
      - sort_column: column name to sort by
      - sort_direction: 'asc' or 'desc' (default 'asc')
      - filters: JSON string of FilterCondition[]
          e.g. [{"column":"brand","operator":"eq","value":"Festool"}]
      - search: text to search across all text/varchar columns (ILIKE)

    Returns:
      { rows, total_rows, filtered_rows, page, page_size }

    Requirements: 3.1, 4.5, 5.3, 5.5, 6.2
    """
    # Validate page_size
    allowed_page_sizes = (25, 50, 100)
    if page_size not in allowed_page_sizes:
        page_size = 50

    # Validate sort_direction
    if sort_direction not in (None, "asc", "desc"):
        sort_direction = "asc"

    pool = get_pool()

    async with pool.acquire() as conn:
        # ---- Build quoted table reference ----
        table_ref = f"{_quote_ident(schema)}.{_quote_ident(table)}"

        # ---- Parse filters ----
        filter_conditions: list[dict] = []
        if filters:
            try:
                filter_conditions = json.loads(filters)
                if not isinstance(filter_conditions, list):
                    filter_conditions = []
            except (json.JSONDecodeError, TypeError):
                filter_conditions = []

        # ---- Build WHERE clauses and params ----
        where_clauses: list[str] = []
        params: list[Any] = []
        param_idx = 1  # asyncpg uses $1, $2, ...

        # Apply filter predicates
        for f in filter_conditions:
            col = f.get("column")
            op = f.get("operator")
            val = f.get("value")

            if not col or not op:
                continue

            quoted_col = _quote_ident(col)

            if op == "eq":
                where_clauses.append(f"{quoted_col} = ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "neq":
                where_clauses.append(f"{quoted_col} != ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "contains":
                where_clauses.append(f"{quoted_col}::text ILIKE ${param_idx}")
                params.append(f"%{val}%")
                param_idx += 1
            elif op == "gt":
                where_clauses.append(f"{quoted_col} > ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "lt":
                where_clauses.append(f"{quoted_col} < ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "is_null":
                where_clauses.append(f"{quoted_col} IS NULL")
            elif op == "has_value":
                where_clauses.append(f"{quoted_col} IS NOT NULL")

        # Apply text search across text/varchar columns
        if search and search.strip():
            # Query information_schema to find text/varchar columns for this table
            text_col_rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = $1
                  AND table_name = $2
                  AND data_type IN ('text', 'character varying', 'character')
                ORDER BY ordinal_position
                """,
                schema,
                table,
            )

            text_columns = [row["column_name"] for row in text_col_rows]

            if text_columns:
                # Build OR clause across all text columns
                or_parts: list[str] = []
                for tc in text_columns:
                    or_parts.append(f"{_quote_ident(tc)} ILIKE ${param_idx}")
                params.append(f"%{search.strip()}%")
                param_idx += 1
                where_clauses.append(f"({' OR '.join(or_parts)})")

        # ---- Assemble WHERE string ----
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        # ---- Get total_rows (unfiltered count) ----
        total_rows_result = await conn.fetchval(
            f"SELECT COUNT(*) FROM {table_ref}"
        )
        total_rows = total_rows_result or 0

        # ---- Get filtered_rows (count with filters/search) ----
        if where_clauses:
            filtered_rows_result = await conn.fetchval(
                f"SELECT COUNT(*) FROM {table_ref} {where_sql}",
                *params,
            )
            filtered_rows = filtered_rows_result or 0
        else:
            filtered_rows = total_rows

        # ---- Build ORDER BY ----
        order_sql = ""
        if sort_column:
            direction = sort_direction or "asc"
            nulls = "NULLS LAST" if direction == "asc" else "NULLS FIRST"
            order_sql = f"ORDER BY {_quote_ident(sort_column)} {direction.upper()} {nulls}"
        else:
            # Default: primary key descending (fallback to ctid if no PK found)
            pk_rows = await conn.fetch(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    AND tc.table_name = kcu.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = $1
                    AND tc.table_name = $2
                ORDER BY kcu.ordinal_position
                """,
                schema,
                table,
            )
            if pk_rows:
                pk_order = ", ".join(
                    f"{_quote_ident(r['column_name'])} DESC" for r in pk_rows
                )
                order_sql = f"ORDER BY {pk_order}"
            else:
                order_sql = "ORDER BY ctid DESC"

        # ---- Build LIMIT/OFFSET ----
        offset = (page - 1) * page_size
        limit_sql = f"LIMIT {page_size} OFFSET {offset}"

        # ---- Execute main query ----
        query = f"SELECT * FROM {table_ref} {where_sql} {order_sql} {limit_sql}"
        rows = await conn.fetch(query, *params)

        # Convert asyncpg Records to dicts using the shared serialization helper
        row_dicts = [_record_to_dict(row) for row in rows]

        return {
            "rows": row_dicts,
            "total_rows": total_rows,
            "filtered_rows": filtered_rows,
            "page": page,
            "page_size": page_size,
        }


# ---- CSV Export --------------------------------------------------------------


@router.get("/{schema}/{table}/export-csv")
async def export_csv(
    schema: str,
    table: str,
    sort_column: Optional[str] = Query(default=None),
    sort_direction: Optional[str] = Query(default=None),
    filters: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user: dict = Depends(require_admin),
) -> StreamingResponse:
    """
    Export all matching rows as a CSV file (streamed).

    Accepts the same filter/sort/search params as get_rows but without pagination —
    all matching rows are included.

    Returns Content-Type: text/csv with Content-Disposition: attachment header.

    Requirements: 30.1
    """
    # Validate sort_direction
    if sort_direction not in (None, "asc", "desc"):
        sort_direction = "asc"

    pool = get_pool()

    async with pool.acquire() as conn:
        # ---- Build quoted table reference ----
        table_ref = f"{_quote_ident(schema)}.{_quote_ident(table)}"

        # ---- Parse filters ----
        filter_conditions: list[dict] = []
        if filters:
            try:
                filter_conditions = json.loads(filters)
                if not isinstance(filter_conditions, list):
                    filter_conditions = []
            except (json.JSONDecodeError, TypeError):
                filter_conditions = []

        # ---- Build WHERE clauses and params ----
        where_clauses: list[str] = []
        params: list[Any] = []
        param_idx = 1

        for f in filter_conditions:
            col = f.get("column")
            op = f.get("operator")
            val = f.get("value")

            if not col or not op:
                continue

            quoted_col = _quote_ident(col)

            if op == "eq":
                where_clauses.append(f"{quoted_col} = ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "neq":
                where_clauses.append(f"{quoted_col} != ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "contains":
                where_clauses.append(f"{quoted_col}::text ILIKE ${param_idx}")
                params.append(f"%{val}%")
                param_idx += 1
            elif op == "gt":
                where_clauses.append(f"{quoted_col} > ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "lt":
                where_clauses.append(f"{quoted_col} < ${param_idx}")
                params.append(val)
                param_idx += 1
            elif op == "is_null":
                where_clauses.append(f"{quoted_col} IS NULL")
            elif op == "has_value":
                where_clauses.append(f"{quoted_col} IS NOT NULL")

        # Apply text search across text/varchar columns
        if search and search.strip():
            text_col_rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = $1
                  AND table_name = $2
                  AND data_type IN ('text', 'character varying', 'character')
                ORDER BY ordinal_position
                """,
                schema,
                table,
            )

            text_columns = [row["column_name"] for row in text_col_rows]

            if text_columns:
                or_parts: list[str] = []
                for tc in text_columns:
                    or_parts.append(f"{_quote_ident(tc)} ILIKE ${param_idx}")
                params.append(f"%{search.strip()}%")
                param_idx += 1
                where_clauses.append(f"({' OR '.join(or_parts)})")

        # ---- Assemble WHERE string ----
        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        # ---- Build ORDER BY ----
        order_sql = ""
        if sort_column:
            direction = sort_direction or "asc"
            nulls = "NULLS LAST" if direction == "asc" else "NULLS FIRST"
            order_sql = f"ORDER BY {_quote_ident(sort_column)} {direction.upper()} {nulls}"
        else:
            pk_rows = await conn.fetch(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    AND tc.table_name = kcu.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = $1
                    AND tc.table_name = $2
                ORDER BY kcu.ordinal_position
                """,
                schema,
                table,
            )
            if pk_rows:
                pk_order = ", ".join(
                    f"{_quote_ident(r['column_name'])} ASC" for r in pk_rows
                )
                order_sql = f"ORDER BY {pk_order}"
            else:
                order_sql = "ORDER BY ctid ASC"

        # ---- Execute query (no LIMIT/OFFSET — all rows) ----
        query = f"SELECT * FROM {table_ref} {where_sql} {order_sql}"
        rows = await conn.fetch(query, *params)

        # ---- Get column names from the first row or from information_schema ----
        if rows:
            columns = list(rows[0].keys())
        else:
            col_rows = await conn.fetch(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = $1 AND table_name = $2
                ORDER BY ordinal_position
                """,
                schema,
                table,
            )
            columns = [r["column_name"] for r in col_rows]

    # ---- Stream CSV response ----
    def _generate_csv():
        """Generator that yields CSV content line by line."""
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header row
        writer.writerow(columns)
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        # Write data rows
        for row in rows:
            csv_row = []
            for col in columns:
                value = _serialize_value(row[col])
                if value is None:
                    csv_row.append("")
                elif isinstance(value, (dict, list)):
                    csv_row.append(json.dumps(value))
                else:
                    csv_row.append(str(value))
            writer.writerow(csv_row)
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    filename = f"{schema}_{table}.csv"

    return StreamingResponse(
        _generate_csv(),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )


# ---- Serialization Helper ----------------------------------------------------


def _record_to_dict(record: asyncpg.Record) -> dict[str, Any]:
    """
    Convert an asyncpg Record to a JSON-serializable dict.

    Handles common Postgres types that aren't natively JSON-serializable:
    - UUID → str
    - datetime/date/time → isoformat string
    - timedelta → total seconds (float)
    - Decimal → float
    - bytes → hex string
    - asyncpg Record → nested dict (recursive)

    This helper is reused by all CRUD endpoints that return row data.
    """
    result: dict[str, Any] = {}
    for key, value in record.items():
        result[key] = _serialize_value(value)
    return result


def _serialize_value(value: Any) -> Any:
    """Recursively serialize a single value to JSON-safe types."""
    if value is None:
        return None
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, asyncpg.Record):
        return _record_to_dict(value)
    if isinstance(value, list):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items()}
    # int, float, str, bool, etc. are already JSON-serializable
    return value


# ---- Create Row --------------------------------------------------------------


@router.post("/{schema}/{table}/rows")
async def create_row(
    schema: str,
    table: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Insert a new row into the specified table and return the created row
    including any generated/default values (e.g., auto-increment PK, timestamps).

    Accepts a JSON body with column_name → value pairs.
    Uses RETURNING * to get the full inserted row back.

    Constraint violations are translated to human-readable HTTP errors:
    - UniqueViolationError → 409 Conflict
    - ForeignKeyViolationError → 400 Bad Request
    - NotNullViolationError → 400 Bad Request
    - CheckViolationError → 400 Bad Request

    Requirements: 12.3, 12.4
    """
    body: dict[str, Any] = await request.json()

    if not body:
        raise HTTPException(status_code=400, detail="Request body must contain at least one field.")

    # Build parameterized INSERT statement with quoted identifiers
    columns = list(body.keys())
    values = list(body.values())

    quoted_schema = f'"{schema}"'
    quoted_table = f'"{table}"'
    quoted_columns = ", ".join(f'"{col}"' for col in columns)
    placeholders = ", ".join(f"${i + 1}" for i in range(len(values)))

    sql = (
        f"INSERT INTO {quoted_schema}.{quoted_table} ({quoted_columns}) "
        f"VALUES ({placeholders}) "
        f"RETURNING *"
    )

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(sql, *values)
    except asyncpg.UniqueViolationError as e:
        detail = str(e.detail) if e.detail else "A record with these values already exists."
        raise HTTPException(
            status_code=409,
            detail=f"Duplicate value: {detail}",
        )
    except asyncpg.ForeignKeyViolationError as e:
        detail = str(e.detail) if e.detail else "Referenced record does not exist."
        raise HTTPException(
            status_code=400,
            detail=f"Foreign key violation: {detail}",
        )
    except asyncpg.NotNullViolationError as e:
        column = e.column_name or "unknown"
        raise HTTPException(
            status_code=400,
            detail=f"Column '{column}' cannot be null.",
        )
    except asyncpg.CheckViolationError as e:
        constraint = e.constraint_name or "unknown"
        raise HTTPException(
            status_code=400,
            detail=f"Check constraint '{constraint}' violated.",
        )

    if row is None:
        raise HTTPException(status_code=500, detail="Insert succeeded but no row was returned.")

    await AuditLogger.log(
        user_id=user['id'],
        action=f'db_browser_create_row',
        target_type='database',
        target_id=None,
        details={"schema": schema, "table": table}
    )
    return _record_to_dict(row)


# ---- Undo logging --------------------------------------------------------


def _undo_actor(request: Request, user: dict) -> tuple[uuid.UUID, int] | None:
    """
    Resolve the (session_id, user_id) needed to record an undo-log entry, or
    None when undo logging should be skipped.

    The session id comes from the ``X-DB-Session-Id`` header and must be a valid
    UUID (``bh_db_browser_undo_log.session_id`` is ``uuid NOT NULL``); the user
    id comes from the authenticated admin and must be an int (``user_id`` is
    ``integer NOT NULL``). Returning None — rather than attempting an insert the
    database rejects — is how callers skip undo without aborting the mutation.

    This replaces the previous code that passed ``str(user_id)`` into the integer
    column, so every undo write raised a DataError that was silently swallowed —
    the undo log was effectively dead (project-review.md C4).
    """
    raw_session = request.headers.get("x-db-session-id")
    if not raw_session:
        return None
    try:
        session_uuid = uuid.UUID(str(raw_session))
    except (ValueError, AttributeError, TypeError):
        logger.warning("Ignoring invalid X-DB-Session-Id header for undo logging")
        return None
    raw_uid = user.get("id") or user.get("user_id")
    try:
        user_id = int(raw_uid)
    except (ValueError, TypeError):
        return None
    return session_uuid, user_id


# ---- Update Row --------------------------------------------------------------


@router.patch("/{schema}/{table}/rows/{row_id}")
async def update_row(
    schema: str,
    table: str,
    row_id: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Update specific fields on a row identified by its primary key.

    Accepts a JSON body with only the fields to update (partial update).
    Builds a dynamic UPDATE ... SET statement with parameterized values.
    Returns the full updated row via RETURNING *.

    Constraint violations are translated to human-readable HTTP errors:
    - UniqueViolationError → 409 Conflict
    - ForeignKeyViolationError → 400 Bad Request
    - NotNullViolationError → 400 Bad Request
    - CheckViolationError → 400 Bad Request

    When X-DB-Session-Id header is present, writes an undo log entry with
    the previous row values before the update is applied.

    Requirements: 7.2, 7.3, 29.6
    """
    body: dict[str, Any] = await request.json()

    if not body:
        raise HTTPException(status_code=400, detail="Request body must contain at least one field to update.")

    pool = get_pool()

    async with pool.acquire() as conn:
        # 1. Determine primary key column
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema,
            table,
        )

        if not pk_rows:
            raise HTTPException(
                status_code=404,
                detail=f"Table {schema}.{table} not found or has no primary key",
            )

        pk_column = pk_rows[0]["column_name"]

        # Cast PK value (most PKs are integer or UUID)
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # 2. Resolve undo actor — if present, fetch current row before update
        undo = _undo_actor(request, user)
        old_row_dict: dict[str, Any] | None = None

        if undo is not None:
            old_row = await conn.fetchrow(
                f"SELECT * FROM {_quote_ident(schema)}.{_quote_ident(table)} "
                f"WHERE {_quote_ident(pk_column)} = $1",
                pk_value,
            )
            if old_row is not None:
                old_row_dict = _record_to_dict(old_row)

        # 3. Build dynamic UPDATE statement
        columns = list(body.keys())
        values = list(body.values())

        set_clauses = []
        for i, col in enumerate(columns):
            set_clauses.append(f"{_quote_ident(col)} = ${i + 1}")

        # PK value is the last parameter
        pk_param_idx = len(values) + 1

        sql = (
            f"UPDATE {_quote_ident(schema)}.{_quote_ident(table)} "
            f"SET {', '.join(set_clauses)} "
            f"WHERE {_quote_ident(pk_column)} = ${pk_param_idx} "
            f"RETURNING *"
        )

        # 4 + 5. Execute the update and record the undo entry atomically: both
        # commit together or neither does, so a failed undo write can never leave
        # an unrecoverable data change (project-review.md C4).
        try:
            async with conn.transaction():
                row = await conn.fetchrow(sql, *values, pk_value)

                if row is None:
                    raise HTTPException(
                        status_code=404,
                        detail=f"Row with {pk_column}={row_id} not found in {schema}.{table}",
                    )

                if undo is not None and old_row_dict is not None:
                    session_uuid, user_id = undo
                    new_values_dict = {k: _serialize_value(body[k]) for k in body}
                    await conn.execute(
                        """
                        INSERT INTO bh_db_browser_undo_log
                            (session_id, user_id, schema_name, table_name, row_id,
                             operation_type, previous_values, new_values)
                        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::jsonb)
                        """,
                        session_uuid,
                        user_id,
                        schema,
                        table,
                        row_id,
                        "update",
                        json.dumps(old_row_dict, default=str),
                        json.dumps(new_values_dict, default=str),
                    )
        except asyncpg.UniqueViolationError as e:
            detail = str(e.detail) if e.detail else "A record with these values already exists."
            raise HTTPException(
                status_code=409,
                detail=f"Duplicate value: {detail}",
            )
        except asyncpg.ForeignKeyViolationError as e:
            detail = str(e.detail) if e.detail else "Referenced record does not exist."
            raise HTTPException(
                status_code=400,
                detail=f"Foreign key violation: {detail}",
            )
        except asyncpg.NotNullViolationError as e:
            column = e.column_name or "unknown"
            raise HTTPException(
                status_code=400,
                detail=f"Column '{column}' cannot be null.",
            )
        except asyncpg.CheckViolationError as e:
            constraint = e.constraint_name or "unknown"
            raise HTTPException(
                status_code=400,
                detail=f"Check constraint '{constraint}' violated.",
            )

        await AuditLogger.log(
            user_id=user['id'],
            action=f'db_browser_update_row',
            target_type='database',
            target_id=None,
            details={"schema": schema, "table": table, "row_id": row_id}
        )
        return _record_to_dict(row)


# ---- Delete Row --------------------------------------------------------------


@router.delete("/{schema}/{table}/rows/{row_id}")
async def delete_row(
    schema: str,
    table: str,
    row_id: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Hard delete a single row by its primary key value.

    If an X-DB-Session-Id header is present, the full row state is captured
    before deletion and written to the undo log so the operation can be reversed.

    Returns 404 if no row matches the given PK value.

    Requirements: 27.4
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # 1. Determine the primary key column
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema,
            table,
        )

        if not pk_rows:
            raise HTTPException(
                status_code=404,
                detail=f"Table {schema}.{table} not found or has no primary key",
            )

        pk_column = pk_rows[0]["column_name"]

        # Cast row_id to int if possible (same pattern as get_row)
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # 2. If undo is active, fetch the full row state BEFORE deleting
        undo = _undo_actor(request, user)
        previous_row: dict[str, Any] | None = None

        if undo is not None:
            row = await conn.fetchrow(
                f"SELECT * FROM {_quote_ident(schema)}.{_quote_ident(table)} "
                f"WHERE {_quote_ident(pk_column)} = $1",
                pk_value,
            )
            if row is not None:
                previous_row = _record_to_dict(row)

        # 3 + 4. Delete the row and record the undo entry atomically.
        delete_query = (
            f"DELETE FROM {_quote_ident(schema)}.{_quote_ident(table)} "
            f"WHERE {_quote_ident(pk_column)} = $1"
        )
        async with conn.transaction():
            result = await conn.execute(delete_query, pk_value)

            # asyncpg returns "DELETE N" where N is the number of rows deleted
            rows_deleted = int(result.split()[-1])

            if rows_deleted == 0:
                raise HTTPException(
                    status_code=404,
                    detail=f"Row with {pk_column}={row_id} not found in {schema}.{table}",
                )

            if undo is not None and previous_row is not None:
                session_uuid, user_id = undo
                await conn.execute(
                    """
                    INSERT INTO bh_db_browser_undo_log
                        (session_id, user_id, schema_name, table_name, row_id,
                         operation_type, previous_values, new_values)
                    VALUES ($1, $2, $3, $4, $5, 'delete', $6::jsonb, NULL)
                    """,
                    session_uuid,
                    user_id,
                    schema,
                    table,
                    row_id,
                    json.dumps(previous_row, default=str),
                )

        # 5. Return success
        await AuditLogger.log(
            user_id=user['id'],
            action=f'db_browser_delete_row',
            target_type='database',
            target_id=None,
            details={"schema": schema, "table": table, "row_id": row_id}
        )
        return {"ok": True, "deleted_id": row_id}


# ---- Bulk Operations ---------------------------------------------------------


@router.post("/{schema}/{table}/bulk-delete")
async def bulk_delete(
    schema: str,
    table: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Delete multiple rows by IDs.

    Body: {"ids": ["id1", "id2", ...]}

    For each ID: fetches the full row state (for undo), deletes the row, and
    writes an undo log entry with operation_type='delete'. The undo session is
    identified by the X-DB-Session-Id header.

    Returns {"ok": true, "deleted_count": N}.

    Requirements: 27.4
    """
    body: dict[str, Any] = await request.json()
    ids = body.get("ids")

    if not ids or not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="Body must contain 'ids' as a non-empty array.")

    pool = get_pool()
    undo = _undo_actor(request, user)

    async with pool.acquire() as conn:
        # 1. Determine the primary key column
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema,
            table,
        )

        if not pk_rows:
            raise HTTPException(
                status_code=404,
                detail=f"Table {schema}.{table} not found or has no primary key",
            )

        pk_column = pk_rows[0]["column_name"]
        deleted_count = 0

        # 2. Process each ID individually to capture undo state. Each row's
        # delete + undo write is atomic (its own transaction) so the batch can
        # still skip non-existent rows while never leaving a deleted row with no
        # undo record (project-review.md C4).
        for raw_id in ids:
            # Cast ID
            try:
                pk_value: Any = int(raw_id)
            except (ValueError, TypeError):
                pk_value = raw_id

            # Fetch full row before deletion (for undo)
            row = await conn.fetchrow(
                f"SELECT * FROM {_quote_ident(schema)}.{_quote_ident(table)} "
                f"WHERE {_quote_ident(pk_column)} = $1",
                pk_value,
            )

            if row is None:
                continue  # Skip rows that don't exist

            previous_row = _record_to_dict(row)

            async with conn.transaction():
                result = await conn.execute(
                    f"DELETE FROM {_quote_ident(schema)}.{_quote_ident(table)} "
                    f"WHERE {_quote_ident(pk_column)} = $1",
                    pk_value,
                )

                rows_affected = int(result.split()[-1])
                if rows_affected > 0 and undo is not None:
                    session_uuid, user_id = undo
                    await conn.execute(
                        """
                        INSERT INTO bh_db_browser_undo_log
                            (session_id, user_id, schema_name, table_name, row_id,
                             operation_type, previous_values, new_values)
                        VALUES ($1, $2, $3, $4, $5, 'delete', $6::jsonb, NULL)
                        """,
                        session_uuid,
                        user_id,
                        schema,
                        table,
                        str(raw_id),
                        json.dumps(previous_row, default=str),
                    )

            if rows_affected > 0:
                deleted_count += 1

        await AuditLogger.log(
            user_id=user['id'],
            action=f'db_browser_bulk_delete',
            target_type='database',
            target_id=None,
            details={"schema": schema, "table": table}
        )
        return {"ok": True, "deleted_count": deleted_count}


@router.post("/{schema}/{table}/bulk-edit")
async def bulk_edit(
    schema: str,
    table: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Update a single field on multiple rows.

    Body: {"ids": ["id1", "id2", ...], "column": "field_name", "value": <any>}

    For each ID: fetches the old value of the target column (for undo), updates
    the single column, and writes an undo log entry with operation_type='bulk_update'.
    The undo session is identified by the X-DB-Session-Id header.

    Returns {"ok": true, "updated_count": N}.

    Requirements: 27.5
    """
    body: dict[str, Any] = await request.json()
    ids = body.get("ids")
    column = body.get("column")
    value = body.get("value")

    if not ids or not isinstance(ids, list):
        raise HTTPException(status_code=400, detail="Body must contain 'ids' as a non-empty array.")
    if not column or not isinstance(column, str):
        raise HTTPException(status_code=400, detail="Body must contain 'column' as a non-empty string.")
    # value can be None (setting to null), so we only validate column and ids

    pool = get_pool()
    undo = _undo_actor(request, user)

    async with pool.acquire() as conn:
        # 1. Determine the primary key column
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema,
            table,
        )

        if not pk_rows:
            raise HTTPException(
                status_code=404,
                detail=f"Table {schema}.{table} not found or has no primary key",
            )

        pk_column = pk_rows[0]["column_name"]
        updated_count = 0

        # 2. Process each ID individually to capture old value for undo. Each
        # row's update + undo write is atomic; constraint failures skip just that
        # row (project-review.md C4).
        for raw_id in ids:
            # Cast ID
            try:
                pk_value: Any = int(raw_id)
            except (ValueError, TypeError):
                pk_value = raw_id

            # Fetch old value of the target column before update
            old_row = await conn.fetchrow(
                f"SELECT {_quote_ident(column)} FROM {_quote_ident(schema)}.{_quote_ident(table)} "
                f"WHERE {_quote_ident(pk_column)} = $1",
                pk_value,
            )

            if old_row is None:
                continue  # Skip rows that don't exist

            old_value = _serialize_value(old_row[column])

            # Update the single column and record undo atomically.
            try:
                async with conn.transaction():
                    result = await conn.execute(
                        f"UPDATE {_quote_ident(schema)}.{_quote_ident(table)} "
                        f"SET {_quote_ident(column)} = $1 "
                        f"WHERE {_quote_ident(pk_column)} = $2",
                        value,
                        pk_value,
                    )

                    rows_affected = int(result.split()[-1])
                    if rows_affected > 0 and undo is not None:
                        session_uuid, user_id = undo
                        await conn.execute(
                            """
                            INSERT INTO bh_db_browser_undo_log
                                (session_id, user_id, schema_name, table_name, row_id,
                                 operation_type, previous_values, new_values)
                            VALUES ($1, $2, $3, $4, $5, 'bulk_update', $6::jsonb, $7::jsonb)
                            """,
                            session_uuid,
                            user_id,
                            schema,
                            table,
                            str(raw_id),
                            json.dumps({column: old_value}, default=str),
                            json.dumps({column: _serialize_value(value)}, default=str),
                        )
            except (
                asyncpg.UniqueViolationError,
                asyncpg.ForeignKeyViolationError,
                asyncpg.NotNullViolationError,
                asyncpg.CheckViolationError,
            ) as e:
                logger.warning(f"Constraint violation during bulk edit (id={raw_id}): {e}")
                continue  # Skip rows that fail constraint checks

            if rows_affected > 0:
                updated_count += 1

        await AuditLogger.log(
            user_id=user['id'],
            action=f'db_browser_bulk_edit',
            target_type='database',
            target_id=None,
            details={"schema": schema, "table": table}
        )
        return {"ok": True, "updated_count": updated_count}


# ---- Lookup Options (FK Dropdown) --------------------------------------------


@router.get("/{schema}/{table}/lookup-options/{column}")
async def get_lookup_options(
    schema: str,
    table: str,
    column: str,
    search: Optional[str] = Query(default=None),
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    Return id + display label pairs for a FK dropdown on the given column.

    Looks up the FK relationship from information_schema, determines a
    human-readable display column from the referenced table, and returns
    options suitable for a dropdown or type-ahead selector.

    Supports `?search=` query param for type-ahead filtering (ILIKE, limit 50).
    Without search, returns up to 500 options ordered by the display column.

    Returns 404 if the column has no FK constraint.

    Requirements: 17.4, 17.5
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # 1. Find the FK relationship for this column
        fk_row = await conn.fetchrow(
            """
            SELECT
                ccu.table_schema AS ref_schema,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.table_constraints tc
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
                AND tc.constraint_type = 'FOREIGN KEY'
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.constraint_schema = tc.constraint_schema
            WHERE kcu.table_schema = $1
              AND kcu.table_name = $2
              AND kcu.column_name = $3
            LIMIT 1
            """,
            schema,
            table,
            column,
        )

        if fk_row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Column '{column}' in {schema}.{table} has no foreign key constraint.",
            )

        ref_schema = fk_row["ref_schema"]
        ref_table = fk_row["ref_table"]
        ref_column = fk_row["ref_column"]

        # 2. Determine the display column from the referenced table
        #    Priority: name → title → description → first text/varchar column → PK column
        col_rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = $1
              AND table_name = $2
            ORDER BY ordinal_position
            """,
            ref_schema,
            ref_table,
        )

        display_column: str | None = None

        # Check for preferred column names
        col_names = {row["column_name"] for row in col_rows}
        for preferred in ("name", "title", "description"):
            if preferred in col_names:
                display_column = preferred
                break

        # Fallback: first text/varchar column
        if display_column is None:
            for row in col_rows:
                if row["data_type"] in ("text", "character varying", "character"):
                    display_column = row["column_name"]
                    break

        # Final fallback: use the PK column itself
        if display_column is None:
            display_column = ref_column

        # 3. Build and execute the query
        table_ref = f"{_quote_ident(ref_schema)}.{_quote_ident(ref_table)}"
        pk_col = _quote_ident(ref_column)
        disp_col = _quote_ident(display_column)

        if search and search.strip():
            # Type-ahead mode: filter by display column, limit 50
            query = (
                f"SELECT {pk_col} AS id, {disp_col} AS label "
                f"FROM {table_ref} "
                f"WHERE {disp_col}::text ILIKE $1 "
                f"ORDER BY {disp_col} "
                f"LIMIT 50"
            )
            rows = await conn.fetch(query, f"%{search.strip()}%")
        else:
            # Full list mode: limit 500 for safety
            query = (
                f"SELECT {pk_col} AS id, {disp_col} AS label "
                f"FROM {table_ref} "
                f"ORDER BY {disp_col} "
                f"LIMIT 500"
            )
            rows = await conn.fetch(query)

        # 4. Serialize results
        return [
            {"id": _serialize_value(row["id"]), "label": _serialize_value(row["label"])}
            for row in rows
        ]


# ---- Image Management --------------------------------------------------------


async def _find_link_table(
    conn: asyncpg.Connection, schema: str, table: str
) -> tuple[str, str] | None:
    """
    Discover the link table name and its FK column pointing to the main table.

    Naming convention: try `{table}_files` first, then singular `{table[:-1]}_files`.
    Returns (link_table_name, fk_column_to_main_table) or None if not found.
    """
    candidates = [f"{table}_files"]
    if table.endswith("s"):
        candidates.append(f"{table[:-1]}_files")

    for candidate in candidates:
        # Check if the candidate table exists in the same schema
        exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = $1 AND table_name = $2
            )
            """,
            schema,
            candidate,
        )
        if not exists:
            continue

        # Find the FK column that points to the main table (not to files.assets)
        fk_row = await conn.fetchrow(
            """
            SELECT kcu.column_name
            FROM information_schema.key_column_usage kcu
            JOIN information_schema.table_constraints tc
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
                AND tc.constraint_type = 'FOREIGN KEY'
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name
                AND ccu.constraint_schema = tc.constraint_schema
            WHERE kcu.table_schema = $1
              AND kcu.table_name = $2
              AND ccu.table_schema = $3
              AND ccu.table_name = $4
            LIMIT 1
            """,
            schema,
            candidate,
            schema,
            table,
        )
        if fk_row:
            return candidate, fk_row["column_name"]

    return None


@router.get("/{schema}/{table}/rows/{row_id}/images")
async def get_row_images(
    schema: str,
    table: str,
    row_id: str,
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    Get all images linked to a specific row via the link table.

    Joins the link table with files.assets to return full asset info.
    Ordered by: is_primary DESC, sort_order ASC, uploaded_at ASC.

    Requirements: 9.1
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # Find the link table
        link_info = await _find_link_table(conn, schema, table)
        if link_info is None:
            return []

        link_table, fk_column = link_info

        # Cast PK value
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # Check which optional columns exist on the link table
        lt_cols_rows = await conn.fetch(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            """,
            schema,
            link_table,
        )
        lt_cols = {r["column_name"] for r in lt_cols_rows}
        has_sort_order = "sort_order" in lt_cols
        has_is_primary = "is_primary" in lt_cols

        # Build SELECT columns dynamically
        select_cols = [
            "a.id AS asset_id",
            "a.path",
            "a.original_name",
            "a.mime",
            "a.ai_summary",
        ]
        if has_is_primary:
            select_cols.append("lt.is_primary")
        else:
            select_cols.append("false AS is_primary")
        if has_sort_order:
            select_cols.append("lt.sort_order")
        else:
            select_cols.append("NULL::int AS sort_order")

        # Build ORDER BY
        order_parts = []
        if has_is_primary:
            order_parts.append("lt.is_primary DESC NULLS LAST")
        if has_sort_order:
            order_parts.append("lt.sort_order ASC NULLS LAST")
        order_parts.append("a.uploaded_at ASC")

        query = f"""
            SELECT {', '.join(select_cols)}
            FROM {_quote_ident(schema)}.{_quote_ident(link_table)} lt
            JOIN files.assets a ON a.id = lt.asset_id
            WHERE lt.{_quote_ident(fk_column)} = $1
            ORDER BY {', '.join(order_parts)}
        """

        rows = await conn.fetch(query, pk_value)

        return [
            {
                "asset_id": str(row["asset_id"]),
                "path": row["path"],
                "original_name": row["original_name"],
                "mime": row["mime"],
                "ai_summary": row["ai_summary"],
                "is_primary": row["is_primary"] if row["is_primary"] is not None else False,
                "sort_order": row["sort_order"],
            }
            for row in rows
        ]


@router.post("/{schema}/{table}/rows/{row_id}/images")
async def upload_row_image(
    schema: str,
    table: str,
    row_id: str,
    request: Request,
    file: UploadFile = File(...),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Upload a file, create an asset record, and link it to the specified row.

    Saves the file to /files/{domain}/{uuid}.{ext} where domain is derived
    from schema/table. Inserts into files.assets and the link table.

    Requirements: 9.2
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # Find the link table
        link_info = await _find_link_table(conn, schema, table)
        if link_info is None:
            raise HTTPException(
                status_code=400,
                detail=f"Table {schema}.{table} does not have an associated link table for images.",
            )

        link_table, fk_column = link_info

        # Cast PK value
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # Read file content
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Empty file uploaded.")

        filename = file.filename or "unnamed"
        mime_type = file.content_type or "application/octet-stream"

        # Derive storage domain from schema/table
        domain = f"{schema}/{table}"

        # Generate unique file path
        ext = Path(filename).suffix.lower() or ".bin"
        asset_id = uuid.uuid4()
        rel_path = f"inventory/{table}/{asset_id}{ext}"

        # Write file to disk
        files_root = Path(os.environ.get("FILES_ROOT", "/files"))
        full_path = files_root / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)

        # Compute sha256 for dedup
        sha256 = hashlib.sha256(content).hexdigest()

        # Insert asset record
        asset_row = await conn.fetchrow(
            """
            INSERT INTO files.assets
                (id, path, original_name, mime, size_bytes, sha256, domain, uploaded_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (sha256) DO UPDATE
                SET path = EXCLUDED.path,
                    original_name = EXCLUDED.original_name
            RETURNING id, path, original_name, mime, ai_summary
            """,
            asset_id,
            rel_path,
            filename,
            mime_type,
            len(content),
            sha256,
            table,  # domain matches table name (tool, saw_blade, etc.)
            str(user.get("id") or user.get("user_id") or "admin"),
        )

        actual_asset_id = asset_row["id"]

        # Determine next sort_order
        max_sort = await conn.fetchval(
            f"""
            SELECT COALESCE(MAX(sort_order), -1)
            FROM {_quote_ident(schema)}.{_quote_ident(link_table)}
            WHERE {_quote_ident(fk_column)} = $1
            """,
            pk_value,
        )
        next_sort = (max_sort or 0) + 1

        # Check if this is the first image (make it primary)
        image_count = await conn.fetchval(
            f"""
            SELECT COUNT(*)
            FROM {_quote_ident(schema)}.{_quote_ident(link_table)}
            WHERE {_quote_ident(fk_column)} = $1
            """,
            pk_value,
        )
        is_primary = image_count == 0

        # Insert link table row
        # Build INSERT dynamically since link tables may or may not have sort_order
        link_columns = await conn.fetch(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            """,
            schema,
            link_table,
        )
        link_col_names = {row["column_name"] for row in link_columns}

        if "sort_order" in link_col_names:
            await conn.execute(
                f"""
                INSERT INTO {_quote_ident(schema)}.{_quote_ident(link_table)}
                    ({_quote_ident(fk_column)}, "asset_id", "is_primary", "sort_order")
                VALUES ($1, $2, $3, $4)
                ON CONFLICT DO NOTHING
                """,
                pk_value,
                actual_asset_id,
                is_primary,
                next_sort,
            )
        else:
            await conn.execute(
                f"""
                INSERT INTO {_quote_ident(schema)}.{_quote_ident(link_table)}
                    ({_quote_ident(fk_column)}, "asset_id", "is_primary")
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                pk_value,
                actual_asset_id,
                is_primary,
            )

        return {
            "asset_id": str(actual_asset_id),
            "path": asset_row["path"],
            "original_name": asset_row["original_name"],
            "mime": asset_row["mime"],
            "ai_summary": asset_row["ai_summary"],
            "is_primary": is_primary,
            "sort_order": next_sort if "sort_order" in link_col_names else None,
        }


@router.put("/{schema}/{table}/rows/{row_id}/images/reorder")
async def reorder_row_images(
    schema: str,
    table: str,
    row_id: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, bool]:
    """
    Reorder images linked to a row by updating sort_order values.

    Accepts JSON body: {"order": [{"asset_id": "...", "sort_order": 0}, ...]}

    Requirements: 9.3
    """
    body = await request.json()
    order_list = body.get("order", [])

    if not order_list:
        raise HTTPException(status_code=400, detail="Request body must contain an 'order' array.")

    pool = get_pool()

    async with pool.acquire() as conn:
        # Find the link table
        link_info = await _find_link_table(conn, schema, table)
        if link_info is None:
            raise HTTPException(
                status_code=400,
                detail=f"Table {schema}.{table} does not have an associated link table.",
            )

        link_table, fk_column = link_info

        # Cast PK value
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # Update sort_order for each asset
        for item in order_list:
            asset_id = item.get("asset_id")
            sort_order = item.get("sort_order")

            if asset_id is None or sort_order is None:
                continue

            await conn.execute(
                f"""
                UPDATE {_quote_ident(schema)}.{_quote_ident(link_table)}
                SET "sort_order" = $1
                WHERE {_quote_ident(fk_column)} = $2 AND "asset_id" = $3::uuid
                """,
                sort_order,
                pk_value,
                asset_id,
            )

    return {"ok": True}


@router.put("/{schema}/{table}/rows/{row_id}/images/{asset_id}/primary")
async def set_primary_image(
    schema: str,
    table: str,
    row_id: str,
    asset_id: str,
    user: dict = Depends(require_admin),
) -> dict[str, bool]:
    """
    Set a specific image as the primary image for a row.

    Sets is_primary = true on the specified link row and
    is_primary = false on all other link rows for this record.

    Requirements: 9.4
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # Find the link table
        link_info = await _find_link_table(conn, schema, table)
        if link_info is None:
            raise HTTPException(
                status_code=400,
                detail=f"Table {schema}.{table} does not have an associated link table.",
            )

        link_table, fk_column = link_info

        # Cast PK value
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # Clear all is_primary for this row
        await conn.execute(
            f"""
            UPDATE {_quote_ident(schema)}.{_quote_ident(link_table)}
            SET "is_primary" = false
            WHERE {_quote_ident(fk_column)} = $1
            """,
            pk_value,
        )

        # Set the specified asset as primary
        result = await conn.execute(
            f"""
            UPDATE {_quote_ident(schema)}.{_quote_ident(link_table)}
            SET "is_primary" = true
            WHERE {_quote_ident(fk_column)} = $1 AND "asset_id" = $2::uuid
            """,
            pk_value,
            asset_id,
        )

        # Check if we actually updated anything
        rows_updated = int(result.split()[-1])
        if rows_updated == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Image {asset_id} not found linked to this row.",
            )

    return {"ok": True}


@router.delete("/{schema}/{table}/rows/{row_id}/images/{asset_id}")
async def unlink_row_image(
    schema: str,
    table: str,
    row_id: str,
    asset_id: str,
    user: dict = Depends(require_admin),
) -> dict[str, bool]:
    """
    Unlink an image from a row by deleting the link table row.

    Does NOT delete the file from disk or the files.assets row.

    Requirements: 9.5
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        # Find the link table
        link_info = await _find_link_table(conn, schema, table)
        if link_info is None:
            raise HTTPException(
                status_code=400,
                detail=f"Table {schema}.{table} does not have an associated link table.",
            )

        link_table, fk_column = link_info

        # Cast PK value
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # Delete the link row
        result = await conn.execute(
            f"""
            DELETE FROM {_quote_ident(schema)}.{_quote_ident(link_table)}
            WHERE {_quote_ident(fk_column)} = $1 AND "asset_id" = $2::uuid
            """,
            pk_value,
            asset_id,
        )

        rows_deleted = int(result.split()[-1])
        if rows_deleted == 0:
            raise HTTPException(
                status_code=404,
                detail=f"Image {asset_id} not found linked to this row.",
            )

    return {"ok": True}


# ---- Layout Configuration ----------------------------------------------------


@router.get("/layouts/{schema}/{table}")
async def get_layout(
    schema: str,
    table: str,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Get per-table layout configuration for the current user.

    Returns list_config and detail_config. If no layout is saved yet,
    returns empty defaults: {list_config: {}, detail_config: {}}.

    Requirements: 10.5
    """
    pool = get_pool()
    user_id = user["id"]

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT list_config, detail_config
            FROM public.bh_db_browser_layouts
            WHERE user_id = $1 AND schema_name = $2 AND table_name = $3
            """,
            user_id,
            schema,
            table,
        )

    if row is None:
        return {"list_config": {}, "detail_config": {}}

    return {
        "list_config": row["list_config"] if row["list_config"] else {},
        "detail_config": row["detail_config"] if row["detail_config"] else {},
    }


@router.put("/layouts/{schema}/{table}")
async def save_layout(
    schema: str,
    table: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Save per-table layout configuration (UPSERT).

    Accepts JSON body with list_config and detail_config.
    Uses INSERT ... ON CONFLICT UPDATE to handle both create and update.

    Requirements: 10.5
    """
    pool = get_pool()
    user_id = user["id"]

    body = await request.json()
    list_config = body.get("list_config", {})
    detail_config = body.get("detail_config", {})

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.bh_db_browser_layouts
                (user_id, schema_name, table_name, list_config, detail_config, updated_at)
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, NOW())
            ON CONFLICT (user_id, schema_name, table_name)
            DO UPDATE SET
                list_config = EXCLUDED.list_config,
                detail_config = EXCLUDED.detail_config,
                updated_at = NOW()
            """,
            user_id,
            schema,
            table,
            json.dumps(list_config),
            json.dumps(detail_config),
        )

    return {
        "list_config": list_config,
        "detail_config": detail_config,
    }


# ---- Field Hints (Configuration) -----------------------------------------------


@router.get("/field-hints")
async def get_field_hints(
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    Return all field hint records from db_admin_field_hints.

    Requirements: 18.4
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT column_name, hint_type, options, prefix, suffix,
                   min_val, max_val, step_val, placeholder, updated_at
            FROM public.db_admin_field_hints
            ORDER BY column_name
            """
        )

    results: list[dict[str, Any]] = []
    for row in rows:
        results.append({
            "column_name": row["column_name"],
            "input_type": row["hint_type"],
            "options": row["options"],
            "prefix": row["prefix"],
            "suffix": row["suffix"],
            "min_val": float(row["min_val"]) if row["min_val"] is not None else None,
            "max_val": float(row["max_val"]) if row["max_val"] is not None else None,
            "step": float(row["step_val"]) if row["step_val"] is not None else None,
            "placeholder": row["placeholder"],
            "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        })

    return results


@router.put("/field-hints/{column_name}")
async def upsert_field_hint(
    column_name: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Upsert a field hint record for a given column name.

    Accepts JSON body with: input_type, options, prefix, suffix, min_val, max_val, step, placeholder.
    Uses INSERT ON CONFLICT UPDATE.

    Requirements: 18.4
    """
    pool = get_pool()
    body = await request.json()

    input_type = body.get("input_type", "text")
    options = body.get("options")
    prefix = body.get("prefix")
    suffix = body.get("suffix")
    min_val = body.get("min_val")
    max_val = body.get("max_val")
    step = body.get("step")
    placeholder = body.get("placeholder")

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO public.db_admin_field_hints
                (column_name, hint_type, options, prefix, suffix, min_val, max_val, step_val, placeholder, updated_at)
            VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, NOW())
            ON CONFLICT (column_name) DO UPDATE SET
                hint_type = EXCLUDED.hint_type,
                options = EXCLUDED.options,
                prefix = EXCLUDED.prefix,
                suffix = EXCLUDED.suffix,
                min_val = EXCLUDED.min_val,
                max_val = EXCLUDED.max_val,
                step_val = EXCLUDED.step_val,
                placeholder = EXCLUDED.placeholder,
                updated_at = NOW()
            """,
            column_name,
            input_type,
            json.dumps(options) if options is not None else None,
            prefix,
            suffix,
            Decimal(str(min_val)) if min_val is not None else None,
            Decimal(str(max_val)) if max_val is not None else None,
            Decimal(str(step)) if step is not None else None,
            placeholder,
        )

    return {
        "ok": True,
        "column_name": column_name,
        "input_type": input_type,
        "options": options,
        "prefix": prefix,
        "suffix": suffix,
        "min_val": min_val,
        "max_val": max_val,
        "step": step,
        "placeholder": placeholder,
    }


@router.delete("/field-hints/{column_name}")
async def delete_field_hint(
    column_name: str,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Delete a field hint record for a given column name.

    Returns 404 if the hint doesn't exist.

    Requirements: 18.4
    """
    pool = get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM public.db_admin_field_hints
            WHERE column_name = $1
            """,
            column_name,
        )

    # asyncpg returns "DELETE N" where N is the number of deleted rows
    if result == "DELETE 0":
        raise HTTPException(
            status_code=404,
            detail=f"No field hint found for column '{column_name}'.",
        )

    return {"ok": True, "column_name": column_name, "deleted": True}


# ---- Saved Views (per-user, per-table) ----------------------------------------


@router.get("/views/{schema}/{table}")
async def list_views(
    schema: str,
    table: str,
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    List all saved views for the current user and the specified schema/table.

    Returns views ordered by created_at ascending so the oldest appear first
    (matching tab order in the UI).

    Requirements: 28.4
    """
    pool = get_pool()
    user_id = user["id"]

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, user_id, schema_name, table_name, name, config, created_at, updated_at
            FROM public.bh_db_browser_views
            WHERE user_id = $1 AND schema_name = $2 AND table_name = $3
            ORDER BY created_at ASC
            """,
            user_id,
            schema,
            table,
        )

    return [_record_to_dict(row) for row in rows]


@router.post("/views/{schema}/{table}")
async def create_view(
    schema: str,
    table: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Create a new saved view for the current user and the specified schema/table.

    Expects JSON body with:
      - name (str, required): display name for the view
      - config (dict, required): view configuration payload containing filters,
        sortColumn, sortDirection, and column visibility settings

    Returns the newly created view record.

    Requirements: 28.4
    """
    pool = get_pool()
    user_id = user["id"]

    body = await request.json()
    name = (body.get("name") or "").strip()
    config = body.get("config", {})

    if not name:
        raise HTTPException(status_code=400, detail="View name is required.")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO public.bh_db_browser_views
                (user_id, schema_name, table_name, name, config)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING id, user_id, schema_name, table_name, name, config, created_at, updated_at
            """,
            user_id,
            schema,
            table,
            name,
            json.dumps(config),
        )

    return _record_to_dict(row)


@router.patch("/views/{schema}/{table}/{view_id}")
async def rename_view(
    schema: str,
    table: str,
    view_id: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Rename an existing saved view.

    Expects JSON body with:
      - name (str, required): new display name for the view

    Returns 404 if the view does not exist or is not owned by the current user.

    Requirements: 28.5
    """
    pool = get_pool()
    user_id = user["id"]

    body = await request.json()
    name = (body.get("name") or "").strip()

    if not name:
        raise HTTPException(status_code=400, detail="View name is required.")

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            UPDATE public.bh_db_browser_views
            SET name = $1, updated_at = NOW()
            WHERE id = $2::uuid AND user_id = $3 AND schema_name = $4 AND table_name = $5
            RETURNING id, user_id, schema_name, table_name, name, config, created_at, updated_at
            """,
            name,
            view_id,
            user_id,
            schema,
            table,
        )

    if row is None:
        raise HTTPException(status_code=404, detail="Saved view not found.")

    return _record_to_dict(row)


@router.delete("/views/{schema}/{table}/{view_id}")
async def delete_view(
    schema: str,
    table: str,
    view_id: str,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Delete a saved view.

    Returns 404 if the view does not exist or is not owned by the current user.

    Requirements: 28.5
    """
    pool = get_pool()
    user_id = user["id"]

    async with pool.acquire() as conn:
        result = await conn.execute(
            """
            DELETE FROM public.bh_db_browser_views
            WHERE id = $1::uuid AND user_id = $2 AND schema_name = $3 AND table_name = $4
            """,
            view_id,
            user_id,
            schema,
            table,
        )

    # asyncpg execute returns a command tag like "DELETE 1" or "DELETE 0"
    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Saved view not found.")

    return {"ok": True, "deleted": True, "view_id": view_id}


# ---- Schema Management (DDL) -------------------------------------------------

# Allowed column type mappings for CREATE TABLE / ADD COLUMN
_COLUMN_TYPE_MAP: dict[str, str] = {
    "text": "TEXT",
    "integer": "INTEGER",
    "decimal": "NUMERIC",
    "numeric": "NUMERIC",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMPTZ",
    "lookup": "INTEGER",
}


def _validate_identifier(name: str, label: str = "name") -> None:
    """
    Validate that a SQL identifier name is safe and reasonable.
    Rejects empty, overly long, or names with disallowed characters.
    """
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail=f"{label} cannot be empty.")
    if len(name) > 63:
        raise HTTPException(
            status_code=400,
            detail=f"{label} exceeds maximum length of 63 characters.",
        )
    # Allow only alphanumeric, underscore, and lowercase chars (Postgres convention)
    if not re.match(r"^[a-z_][a-z0-9_]*$", name):
        raise HTTPException(
            status_code=400,
            detail=f"{label} must start with a letter or underscore and contain only lowercase letters, digits, and underscores.",
        )


# Bare SQL defaults we explicitly allow (matched case-insensitively). Anything
# not in this set is emitted as a validated numeric literal or a single-quoted
# string literal, so a crafted "default" can never break out of the DEFAULT
# clause into arbitrary SQL.
_ALLOWED_DEFAULT_KEYWORDS: dict[str, str] = {
    "NULL": "NULL",
    "TRUE": "TRUE",
    "FALSE": "FALSE",
    "NOW()": "NOW()",
    "CURRENT_TIMESTAMP": "CURRENT_TIMESTAMP",
    "CURRENT_DATE": "CURRENT_DATE",
    "CURRENT_TIME": "CURRENT_TIME",
    "GEN_RANDOM_UUID()": "gen_random_uuid()",
}


def _safe_default_literal(default: Any) -> str:
    """
    Render a user-supplied column DEFAULT as a SQL fragment that cannot inject.

    The value is matched against a small allow-list of bare SQL keywords /
    functions, then a numeric-literal pattern, then a well-formed single-quoted
    string literal; anything else is emitted as a single-quoted string literal
    with interior quotes doubled. A crafted value like ``0); DROP TABLE x; --``
    therefore becomes the harmless literal ``'0); DROP TABLE x; --'`` rather than
    executable SQL.

    This closes the raw-interpolation sink at the DEFAULT clause that previously
    appended ``DEFAULT {default_str}`` verbatim (project-review.md C4).
    """
    raw = str(default).strip()

    canonical = _ALLOWED_DEFAULT_KEYWORDS.get(raw.upper())
    if canonical is not None:
        return canonical

    # Plain numeric literal (int or decimal) — safe to emit verbatim.
    if re.fullmatch(r"-?\d+(\.\d+)?", raw):
        return raw

    # A well-formed single-quoted literal (only doubled interior quotes) is fine
    # as-is; this preserves callers that already pass quoted string defaults.
    if (
        len(raw) >= 2
        and raw[0] == "'"
        and raw[-1] == "'"
        and "'" not in raw[1:-1].replace("''", "")
    ):
        return raw

    # Fallback: treat the whole value as a string literal.
    return "'" + raw.replace("'", "''") + "'"


def _build_column_sql(col: dict[str, Any]) -> str:
    """
    Build a single column definition for CREATE TABLE or ADD COLUMN.

    Accepts: {name, type, nullable?, default?, fk_schema?, fk_table?, fk_column?}
    Returns the SQL fragment like: "price" NUMERIC NOT NULL DEFAULT 0
    """
    col_name = col.get("name", "").strip().lower()
    col_type = col.get("type", "text").strip().lower()
    nullable = col.get("nullable", True)
    default = col.get("default")

    if not col_name:
        raise HTTPException(status_code=400, detail="Column name cannot be empty.")

    _validate_identifier(col_name, f"Column name '{col_name}'")

    # Map type name to SQL type
    sql_type = _COLUMN_TYPE_MAP.get(col_type)
    if sql_type is None:
        allowed = ", ".join(sorted(_COLUMN_TYPE_MAP.keys()))
        raise HTTPException(
            status_code=400,
            detail=f"Unknown column type '{col_type}'. Allowed types: {allowed}.",
        )

    parts = [_quote_ident(col_name), sql_type]

    if not nullable:
        parts.append("NOT NULL")

    if default is not None and str(default).strip():
        # Render the default as a safe, validated SQL fragment (no raw interpolation).
        parts.append(f"DEFAULT {_safe_default_literal(default)}")

    return " ".join(parts)


def _build_fk_constraint(col: dict[str, Any], table_name: str) -> str | None:
    """
    Build a FK CONSTRAINT clause for a lookup column.
    Returns None if the column is not a lookup type or FK info is missing.
    """
    col_type = col.get("type", "").strip().lower()
    if col_type != "lookup":
        return None

    fk_schema = col.get("fk_schema", "").strip()
    fk_table = col.get("fk_table", "").strip()
    fk_column = col.get("fk_column", "id").strip()
    col_name = col.get("name", "").strip().lower()

    if not fk_schema or not fk_table:
        raise HTTPException(
            status_code=400,
            detail=f"Lookup column '{col_name}' requires fk_schema and fk_table.",
        )

    constraint_name = f"fk_{table_name}_{col_name}"
    return (
        f"CONSTRAINT {_quote_ident(constraint_name)} "
        f"FOREIGN KEY ({_quote_ident(col_name)}) "
        f"REFERENCES {_quote_ident(fk_schema)}.{_quote_ident(fk_table)}({_quote_ident(fk_column)})"
    )


def _build_create_table_sql(
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    include_image_support: bool = False,
) -> str:
    """
    Build the full CREATE TABLE SQL including columns, constraints, and
    optionally the link table for image support.

    Returns the complete SQL string (may contain multiple statements).
    """
    if not columns:
        raise HTTPException(status_code=400, detail="At least one column is required.")

    # Always start with a serial PK
    col_definitions = [f"{_quote_ident('id')} SERIAL PRIMARY KEY"]
    fk_constraints: list[str] = []

    for col in columns:
        col_definitions.append(_build_column_sql(col))
        fk = _build_fk_constraint(col, table)
        if fk:
            fk_constraints.append(fk)

    # Add created_at and updated_at timestamps
    col_definitions.append('"created_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()')
    col_definitions.append('"updated_at" TIMESTAMPTZ NOT NULL DEFAULT NOW()')

    all_parts = col_definitions + fk_constraints
    columns_sql = ",\n  ".join(all_parts)

    table_ref = f"{_quote_ident(schema)}.{_quote_ident(table)}"
    statements = [f"CREATE TABLE {table_ref} (\n  {columns_sql}\n);"]

    # Optional link table for image support
    if include_image_support:
        # Singular form of table name for FK column name
        singular = table[:-1] if table.endswith("s") else table
        fk_col = f"{singular}_id"
        link_table = f"{table}_files"
        link_ref = f"{_quote_ident(schema)}.{_quote_ident(link_table)}"

        link_sql = (
            f"CREATE TABLE {link_ref} (\n"
            f"  {_quote_ident(fk_col)} INTEGER NOT NULL REFERENCES {table_ref}(\"id\") ON DELETE CASCADE,\n"
            f"  \"asset_id\" UUID NOT NULL REFERENCES files.assets(\"id\") ON DELETE CASCADE,\n"
            f"  \"is_primary\" BOOLEAN DEFAULT false,\n"
            f"  \"sort_order\" INTEGER DEFAULT 0,\n"
            f"  PRIMARY KEY ({_quote_ident(fk_col)}, \"asset_id\")\n"
            f");"
        )
        statements.append(link_sql)

    return "\n\n".join(statements)


@router.post("/schemas")
async def create_schema(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Create a new database schema.

    Body: {"name": "schema_name"}
    Returns 409 if the schema already exists.

    Requirements: 15.2, 15.3
    """
    body = await request.json()
    name = (body.get("name") or "").strip().lower()

    _validate_identifier(name, "Schema name")

    pool = get_pool()

    async with pool.acquire() as conn:
        # Check if schema already exists
        exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = $1
            )
            """,
            name,
        )

        if exists:
            raise HTTPException(
                status_code=409,
                detail=f"Schema '{name}' already exists.",
            )

        # Execute CREATE SCHEMA
        sql = f"CREATE SCHEMA {_quote_ident(name)}"
        try:
            await conn.execute(sql)
        except Exception as e:
            logger.error(f"Failed to create schema '{name}': {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create schema: {e}",
            )

    await AuditLogger.log(
        user_id=user['id'],
        action=f'db_browser_create_schema',
        target_type='database',
        target_id=None,
        details={"schema": name}
    )
    return {"ok": True, "schema": name, "sql": sql}


@router.post("/tables")
async def create_table(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Create a new table with the specified columns.

    Body: {
        "schema": "inventory",
        "table": "widgets",
        "columns": [{"name": "brand", "type": "text", "nullable": true, "default": null}],
        "include_image_support": true
    }

    If include_image_support is true, also creates a `{schema}.{table}_files` link table.

    Column type values: text, integer, decimal, boolean, date, timestamp, lookup.
    Lookup type requires additional fk_schema, fk_table, fk_column fields.

    Requirements: 14.6, 16.2
    """
    body = await request.json()

    schema = (body.get("schema") or "").strip().lower()
    table = (body.get("table") or "").strip().lower()
    columns = body.get("columns", [])
    include_image_support = body.get("include_image_support", False)

    _validate_identifier(schema, "Schema name")
    _validate_identifier(table, "Table name")

    if not columns or not isinstance(columns, list):
        raise HTTPException(status_code=400, detail="At least one column is required.")

    # Build the SQL
    sql = _build_create_table_sql(schema, table, columns, include_image_support)

    pool = get_pool()

    async with pool.acquire() as conn:
        # Check if schema exists
        schema_exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.schemata
                WHERE schema_name = $1
            )
            """,
            schema,
        )
        if not schema_exists:
            raise HTTPException(
                status_code=400,
                detail=f"Schema '{schema}' does not exist. Create it first.",
            )

        # Check if table already exists
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = $1 AND table_name = $2
            )
            """,
            schema,
            table,
        )
        if table_exists:
            raise HTTPException(
                status_code=409,
                detail=f"Table '{schema}.{table}' already exists.",
            )

        # Execute the DDL
        try:
            await conn.execute(sql)
        except asyncpg.DuplicateTableError:
            raise HTTPException(
                status_code=409,
                detail=f"Table '{schema}.{table}' already exists.",
            )
        except Exception as e:
            logger.error(f"Failed to create table '{schema}.{table}': {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create table: {e}",
            )

    await AuditLogger.log(
        user_id=user['id'],
        action=f'db_browser_create_table',
        target_type='database',
        target_id=None,
        details={"schema": schema, "table": table}
    )
    return {"ok": True, "schema": schema, "table": table, "sql": sql}


@router.post("/tables/{schema}/{table}/preview")
async def preview_create_table(
    schema: str,
    table: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, str]:
    """
    Generate the CREATE TABLE SQL without executing it.

    Same body as POST /tables but only returns the SQL string for user review.
    Useful for showing a live SQL preview in the UI before committing.

    Requirements: 14.4
    """
    body = await request.json()

    # Allow schema/table from path or body (path takes precedence for this endpoint)
    req_schema = schema.strip().lower()
    req_table = table.strip().lower()
    columns = body.get("columns", [])
    include_image_support = body.get("include_image_support", False)

    _validate_identifier(req_schema, "Schema name")
    _validate_identifier(req_table, "Table name")

    if not columns or not isinstance(columns, list):
        raise HTTPException(status_code=400, detail="At least one column is required.")

    # Build the SQL (no execution)
    sql = _build_create_table_sql(req_schema, req_table, columns, include_image_support)

    return {"sql": sql}


@router.patch("/tables/{schema}/{table}")
async def alter_table(
    schema: str,
    table: str,
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Perform schema management operations on an existing table.

    Body: {"action": "<action_name>", ...params}

    Supported actions:
      - rename: {"action": "rename", "new_name": "new_table_name"}
      - move_schema: {"action": "move_schema", "new_schema": "target_schema"}
      - add_column: {"action": "add_column", "name": "col", "type": "text", "nullable": true, "default": null}
      - drop_column: {"action": "drop_column", "column_name": "col_to_drop"}

    Uses _quote_ident for all identifiers to prevent SQL injection.

    Requirements: 16.2, 16.3, 16.4, 16.5
    """
    body = await request.json()
    action = (body.get("action") or "").strip().lower()

    if not action:
        raise HTTPException(status_code=400, detail="Missing 'action' field.")

    pool = get_pool()
    table_ref = f"{_quote_ident(schema)}.{_quote_ident(table)}"

    async with pool.acquire() as conn:
        # Verify the table exists before performing any action
        table_exists = await conn.fetchval(
            """
            SELECT EXISTS(
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = $1 AND table_name = $2
            )
            """,
            schema,
            table,
        )
        if not table_exists:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{schema}.{table}' not found.",
            )

        if action == "rename":
            new_name = (body.get("new_name") or "").strip().lower()
            _validate_identifier(new_name, "New table name")

            sql = f"ALTER TABLE {table_ref} RENAME TO {_quote_ident(new_name)}"
            try:
                await conn.execute(sql)
            except asyncpg.DuplicateTableError:
                raise HTTPException(
                    status_code=409,
                    detail=f"A table named '{new_name}' already exists in schema '{schema}'.",
                )
            except Exception as e:
                logger.error(f"Failed to rename table: {e}")
                raise HTTPException(status_code=500, detail=f"Failed to rename table: {e}")

            return {"ok": True, "action": "rename", "old_name": table, "new_name": new_name, "sql": sql}

        elif action == "move_schema":
            new_schema = (body.get("new_schema") or "").strip().lower()
            _validate_identifier(new_schema, "Target schema name")

            # Check that the target schema exists
            schema_exists = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.schemata
                    WHERE schema_name = $1
                )
                """,
                new_schema,
            )
            if not schema_exists:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target schema '{new_schema}' does not exist.",
                )

            sql = f"ALTER TABLE {table_ref} SET SCHEMA {_quote_ident(new_schema)}"
            try:
                await conn.execute(sql)
            except Exception as e:
                logger.error(f"Failed to move table to schema '{new_schema}': {e}")
                raise HTTPException(status_code=500, detail=f"Failed to move table: {e}")

            return {
                "ok": True,
                "action": "move_schema",
                "old_schema": schema,
                "new_schema": new_schema,
                "table": table,
                "sql": sql,
            }

        elif action == "add_column":
            col_name = (body.get("name") or "").strip().lower()
            col_type = (body.get("type") or "text").strip().lower()
            nullable = body.get("nullable", True)
            default = body.get("default")
            fk_schema = (body.get("fk_schema") or "").strip()
            fk_table = (body.get("fk_table") or "").strip()
            fk_column = (body.get("fk_column") or "id").strip()

            col_def = _build_column_sql({
                "name": col_name,
                "type": col_type,
                "nullable": nullable,
                "default": default,
            })

            sql = f"ALTER TABLE {table_ref} ADD COLUMN {col_def}"

            # If it's a lookup, add FK constraint
            fk_sql: str | None = None
            if col_type == "lookup" and fk_schema and fk_table:
                constraint_name = f"fk_{table}_{col_name}"
                fk_sql = (
                    f"ALTER TABLE {table_ref} ADD CONSTRAINT {_quote_ident(constraint_name)} "
                    f"FOREIGN KEY ({_quote_ident(col_name)}) "
                    f"REFERENCES {_quote_ident(fk_schema)}.{_quote_ident(fk_table)}({_quote_ident(fk_column)})"
                )

            try:
                await conn.execute(sql)
                if fk_sql:
                    await conn.execute(fk_sql)
            except asyncpg.DuplicateColumnError:
                raise HTTPException(
                    status_code=409,
                    detail=f"Column '{col_name}' already exists in '{schema}.{table}'.",
                )
            except Exception as e:
                logger.error(f"Failed to add column '{col_name}': {e}")
                raise HTTPException(status_code=500, detail=f"Failed to add column: {e}")

            full_sql = sql + (";\n" + fk_sql if fk_sql else "")
            return {"ok": True, "action": "add_column", "column": col_name, "sql": full_sql}

        elif action == "drop_column":
            column_name = (body.get("column_name") or "").strip().lower()
            if not column_name:
                raise HTTPException(status_code=400, detail="Missing 'column_name' for drop_column action.")

            # Prevent dropping the PK column
            pk_rows = await conn.fetch(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    AND tc.table_name = kcu.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = $1
                    AND tc.table_name = $2
                """,
                schema,
                table,
            )
            pk_columns = {row["column_name"] for row in pk_rows}

            if column_name in pk_columns:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot drop primary key column '{column_name}'.",
                )

            # Verify column exists
            col_exists = await conn.fetchval(
                """
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.columns
                    WHERE table_schema = $1 AND table_name = $2 AND column_name = $3
                )
                """,
                schema,
                table,
                column_name,
            )
            if not col_exists:
                raise HTTPException(
                    status_code=404,
                    detail=f"Column '{column_name}' not found in '{schema}.{table}'.",
                )

            sql = f"ALTER TABLE {table_ref} DROP COLUMN {_quote_ident(column_name)}"
            try:
                await conn.execute(sql)
            except Exception as e:
                logger.error(f"Failed to drop column '{column_name}': {e}")
                raise HTTPException(status_code=500, detail=f"Failed to drop column: {e}")

            await AuditLogger.log(
                user_id=user['id'],
                action=f'db_browser_alter_table',
                target_type='database',
                target_id=None,
                details={"schema": schema, "table": table, "action": action}
            )
            return {"ok": True, "action": "drop_column", "column": column_name, "sql": sql}

        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown action '{action}'. Supported: rename, move_schema, add_column, drop_column.",
            )


# ---- Undo / Redo -------------------------------------------------------------


@router.post("/undo")
async def undo_operation(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Undo the last non-undone operation for the current session.

    Reads the X-DB-Session-Id header to identify the session. Finds the most
    recent entry in bh_db_browser_undo_log that has is_undone=false for this
    session. Reverses the operation:
      - 'update' / 'bulk_update': PATCH the row back to previous_values
      - 'insert': DELETE the row
      - 'delete': INSERT the row back using previous_values

    Marks the entry as is_undone=true and returns the entry.

    Requirements: 29.1, 29.5, 29.7
    """
    session_id = request.headers.get("x-db-session-id")
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="Missing X-DB-Session-Id header.",
        )

    pool = get_pool()

    async with pool.acquire() as conn:
        # Find the latest non-undone entry for this session
        entry = await conn.fetchrow(
            """
            SELECT id, session_id, schema_name, table_name, row_id,
                   operation_type, previous_values, new_values, is_undone, created_at
            FROM bh_db_browser_undo_log
            WHERE session_id = $1::uuid AND is_undone = false
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            session_id,
        )

        if entry is None:
            raise HTTPException(
                status_code=404,
                detail="Nothing to undo for this session.",
            )

        schema_name = entry["schema_name"]
        table_name = entry["table_name"]
        row_id = entry["row_id"]
        operation_type = entry["operation_type"]
        previous_values = entry["previous_values"]
        new_values = entry["new_values"]
        table_ref = f"{_quote_ident(schema_name)}.{_quote_ident(table_name)}"

        # Determine primary key column for this table
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema_name,
            table_name,
        )

        if not pk_rows:
            raise HTTPException(
                status_code=500,
                detail=f"Table {schema_name}.{table_name} has no primary key; cannot undo.",
            )

        pk_column = pk_rows[0]["column_name"]

        # Cast PK value
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # Reverse the operation
        if operation_type in ("update", "bulk_update"):
            # PATCH the row back to previous_values
            if not previous_values:
                raise HTTPException(
                    status_code=500,
                    detail="Cannot undo update: no previous values recorded.",
                )

            # Only update the columns that were changed (those in new_values)
            cols_to_revert = list(new_values.keys()) if new_values else list(previous_values.keys())
            set_clauses = []
            params: list[Any] = []
            for i, col in enumerate(cols_to_revert):
                set_clauses.append(f"{_quote_ident(col)} = ${i + 1}")
                params.append(previous_values.get(col))

            pk_param_idx = len(params) + 1
            params.append(pk_value)

            sql = (
                f"UPDATE {table_ref} SET {', '.join(set_clauses)} "
                f"WHERE {_quote_ident(pk_column)} = ${pk_param_idx}"
            )
            await conn.execute(sql, *params)

        elif operation_type == "insert":
            # DELETE the row that was inserted
            await conn.execute(
                f"DELETE FROM {table_ref} WHERE {_quote_ident(pk_column)} = $1",
                pk_value,
            )

        elif operation_type == "delete":
            # INSERT the row back using previous_values
            if not previous_values:
                raise HTTPException(
                    status_code=500,
                    detail="Cannot undo delete: no previous values recorded.",
                )

            columns = list(previous_values.keys())
            values = list(previous_values.values())
            col_list = ", ".join(_quote_ident(c) for c in columns)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(values)))

            sql = f"INSERT INTO {table_ref} ({col_list}) VALUES ({placeholders})"
            try:
                await conn.execute(sql, *values)
            except asyncpg.UniqueViolationError:
                # Row already exists (possible duplicate undo attempt)
                raise HTTPException(
                    status_code=409,
                    detail="Cannot undo delete: row already exists (possible duplicate undo).",
                )

        else:
            raise HTTPException(
                status_code=500,
                detail=f"Unknown operation type '{operation_type}' in undo log.",
            )

        # Mark the entry as undone
        await conn.execute(
            "UPDATE bh_db_browser_undo_log SET is_undone = true WHERE id = $1",
            entry["id"],
        )

        # Return the undone entry
        await AuditLogger.log(
            user_id=user['id'],
            action=f'db_browser_undo_operation',
            target_type='database',
            target_id=None,
            details={"session_id": session_id}
        )
        return _record_to_dict(entry)


@router.post("/redo")
async def redo_operation(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Redo the last undone operation for the current session.

    Reads the X-DB-Session-Id header. Finds the most recent entry in
    bh_db_browser_undo_log that has is_undone=true for this session.
    Re-applies the operation:
      - 'update' / 'bulk_update': PATCH the row to new_values
      - 'insert': INSERT the row again using new_values (or previous_values for PK)
      - 'delete': DELETE the row again

    Marks the entry as is_undone=false and returns the entry.

    Requirements: 29.1, 29.5, 29.7
    """
    session_id = request.headers.get("x-db-session-id")
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="Missing X-DB-Session-Id header.",
        )

    pool = get_pool()

    async with pool.acquire() as conn:
        # Find the latest undone entry for this session
        entry = await conn.fetchrow(
            """
            SELECT id, session_id, schema_name, table_name, row_id,
                   operation_type, previous_values, new_values, is_undone, created_at
            FROM bh_db_browser_undo_log
            WHERE session_id = $1::uuid AND is_undone = true
            ORDER BY created_at ASC, id ASC
            LIMIT 1
            """,
            session_id,
        )

        if entry is None:
            raise HTTPException(
                status_code=404,
                detail="Nothing to redo for this session.",
            )

        schema_name = entry["schema_name"]
        table_name = entry["table_name"]
        row_id = entry["row_id"]
        operation_type = entry["operation_type"]
        previous_values = entry["previous_values"]
        new_values = entry["new_values"]
        table_ref = f"{_quote_ident(schema_name)}.{_quote_ident(table_name)}"

        # Determine primary key column
        pk_rows = await conn.fetch(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
                AND tc.table_schema = $1
                AND tc.table_name = $2
            ORDER BY kcu.ordinal_position
            """,
            schema_name,
            table_name,
        )

        if not pk_rows:
            raise HTTPException(
                status_code=500,
                detail=f"Table {schema_name}.{table_name} has no primary key; cannot redo.",
            )

        pk_column = pk_rows[0]["column_name"]

        # Cast PK value
        try:
            pk_value: Any = int(row_id)
        except ValueError:
            pk_value = row_id

        # Re-apply the operation
        if operation_type in ("update", "bulk_update"):
            # PATCH the row to new_values
            if not new_values:
                raise HTTPException(
                    status_code=500,
                    detail="Cannot redo update: no new values recorded.",
                )

            columns = list(new_values.keys())
            set_clauses = []
            params: list[Any] = []
            for i, col in enumerate(columns):
                set_clauses.append(f"{_quote_ident(col)} = ${i + 1}")
                params.append(new_values[col])

            pk_param_idx = len(params) + 1
            params.append(pk_value)

            sql = (
                f"UPDATE {table_ref} SET {', '.join(set_clauses)} "
                f"WHERE {_quote_ident(pk_column)} = ${pk_param_idx}"
            )
            await conn.execute(sql, *params)

        elif operation_type == "insert":
            # INSERT the row again
            # For inserts, new_values contains the row that was inserted
            # Use previous_values as fallback (delete-undo stores full row there)
            row_data = new_values or previous_values
            if not row_data:
                raise HTTPException(
                    status_code=500,
                    detail="Cannot redo insert: no row data recorded.",
                )

            columns = list(row_data.keys())
            values = list(row_data.values())
            col_list = ", ".join(_quote_ident(c) for c in columns)
            placeholders = ", ".join(f"${i + 1}" for i in range(len(values)))

            sql = f"INSERT INTO {table_ref} ({col_list}) VALUES ({placeholders})"
            try:
                await conn.execute(sql, *values)
            except asyncpg.UniqueViolationError:
                raise HTTPException(
                    status_code=409,
                    detail="Cannot redo insert: row already exists.",
                )

        elif operation_type == "delete":
            # DELETE the row again
            await conn.execute(
                f"DELETE FROM {table_ref} WHERE {_quote_ident(pk_column)} = $1",
                pk_value,
            )

        else:
            raise HTTPException(
                status_code=500,
                detail=f"Unknown operation type '{operation_type}' in undo log.",
            )

        # Mark the entry as not undone (re-done)
        await conn.execute(
            "UPDATE bh_db_browser_undo_log SET is_undone = false WHERE id = $1",
            entry["id"],
        )

        # Return the redone entry
        await AuditLogger.log(
            user_id=user['id'],
            action=f'db_browser_redo_operation',
            target_type='database',
            target_id=None,
            details={"session_id": session_id}
        )
        return _record_to_dict(entry)


@router.post("/undo/clear-session")
async def clear_undo_session(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Clear all undo log entries for the current session.

    Called when the user navigates away from the DB Browser to clean up
    the session's undo history.

    Requirements: 29.7
    """
    session_id = request.headers.get("x-db-session-id")
    if not session_id:
        raise HTTPException(
            status_code=400,
            detail="Missing X-DB-Session-Id header.",
        )

    pool = get_pool()

    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM bh_db_browser_undo_log WHERE session_id = $1::uuid",
            session_id,
        )

        # asyncpg returns "DELETE N" where N is the count
        cleared_count = int(result.split()[-1])

        return {"ok": True, "cleared_count": cleared_count}


# ---- Relations ---------------------------------------------------------------


@router.get("/{schema}/{table}/{row_id}/relations")
async def get_relations(
    schema: str,
    table: str,
    row_id: str,
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    Return all tables that have foreign key columns referencing the target table,
    along with the count of related rows and up to 5 most recent rows for each.

    Queries information_schema.table_constraints and key_column_usage to discover
    FK references dynamically — no hardcoded knowledge of table relationships.

    Returns: RelationGroup[] where each entry has:
      - schema: the referencing table's schema
      - table: the referencing table's name
      - fk_column: the FK column in the referencing table
      - total_count: total rows where fk_column = row_id
      - rows: up to 5 most recent rows (ordered by PK DESC)

    Requirements: 31.1, 31.5
    """
    pool = get_pool()

    # Cast row_id to the appropriate Python type (int if possible, else string)
    try:
        pk_value: Any = int(row_id)
    except ValueError:
        pk_value = row_id

    async with pool.acquire() as conn:
        # ---- Step 1: Find all FK references pointing to this table ----
        # We look for constraints where the referenced table matches our target.
        fk_refs = await conn.fetch(
            """
            SELECT
                ccu.table_schema AS ref_schema,
                ccu.table_name AS ref_table,
                ccu.column_name AS ref_column,
                kcu.table_schema AS fk_schema,
                kcu.table_name AS fk_table,
                kcu.column_name AS fk_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
                AND tc.constraint_schema = ccu.constraint_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_schema = $1
              AND ccu.table_name = $2
            ORDER BY kcu.table_schema, kcu.table_name, kcu.column_name
            """,
            schema,
            table,
        )

        if not fk_refs:
            return []

        # ---- Step 2: For each referencing table, get count + 5 recent rows ----
        relation_groups: list[dict[str, Any]] = []

        for ref in fk_refs:
            fk_schema = ref["fk_schema"]
            fk_table = ref["fk_table"]
            fk_column = ref["fk_column"]

            fk_table_ref = f"{_quote_ident(fk_schema)}.{_quote_ident(fk_table)}"
            fk_col_quoted = _quote_ident(fk_column)

            # Get total count of related rows
            count_query = f"SELECT COUNT(*) FROM {fk_table_ref} WHERE {fk_col_quoted} = $1"
            total_count = await conn.fetchval(count_query, pk_value) or 0

            if total_count == 0:
                # Still include in results so the UI can show the "Add" button
                relation_groups.append({
                    "schema": fk_schema,
                    "table": fk_table,
                    "fk_column": fk_column,
                    "total_count": 0,
                    "rows": [],
                })
                continue

            # Find the PK column(s) of the referencing table for ORDER BY
            pk_rows = await conn.fetch(
                """
                SELECT kcu.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                    AND tc.table_name = kcu.table_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                    AND tc.table_schema = $1
                    AND tc.table_name = $2
                ORDER BY kcu.ordinal_position
                """,
                fk_schema,
                fk_table,
            )

            if pk_rows:
                order_clause = ", ".join(
                    f"{_quote_ident(r['column_name'])} DESC" for r in pk_rows
                )
            else:
                order_clause = "ctid DESC"

            # Fetch up to 5 most recent related rows
            rows_query = (
                f"SELECT * FROM {fk_table_ref} "
                f"WHERE {fk_col_quoted} = $1 "
                f"ORDER BY {order_clause} "
                f"LIMIT 5"
            )
            rows = await conn.fetch(rows_query, pk_value)

            relation_groups.append({
                "schema": fk_schema,
                "table": fk_table,
                "fk_column": fk_column,
                "total_count": total_count,
                "rows": [_record_to_dict(r) for r in rows],
            })

        return relation_groups


# ---- CSV Import --------------------------------------------------------------


def _cast_value(val: Any, data_type: str) -> Any:
    """
    Cast a string value from CSV to the appropriate Python type for asyncpg.

    Handles: boolean, date, timestamp, integer, numeric/decimal, and passes
    through text types as-is. Returns None for empty strings or null-like values.
    """
    if val is None:
        return None

    # Treat empty strings as NULL
    if isinstance(val, str) and val.strip() == "":
        return None

    if data_type == "boolean":
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "yes", "t")

    if data_type == "date":
        if isinstance(val, date):
            return val
        try:
            return date.fromisoformat(str(val).split("T")[0])
        except (ValueError, AttributeError):
            return None

    if data_type in (
        "timestamp with time zone",
        "timestamp without time zone",
        "timestamptz",
        "timestamp",
    ):
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val))
        except (ValueError, AttributeError):
            return None

    if data_type in ("integer", "bigint", "smallint"):
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    if data_type in ("numeric", "real", "double precision"):
        try:
            return Decimal(str(val))
        except Exception:
            return None

    # text, character varying, uuid, etc. — pass through as string
    return str(val)


@router.post("/{schema}/{table}/import-csv")
async def import_csv(
    schema: str,
    table: str,
    file: UploadFile = File(...),
    mapping: str = Form(...),
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Import rows from a CSV file into the specified table.

    Accepts multipart form data with:
      - file: the CSV file to import
      - mapping: JSON string describing column mapping
        Shape: { "csv_column_name": "table_column_name" | null }
        A null value means skip that CSV column.

    The endpoint parses the CSV, applies the column mapping, casts values
    based on the target column's Postgres data type, and inserts row-by-row.
    On constraint violations, the error is recorded and the import continues
    with the next row.

    Returns:
      { total_rows: int, imported_rows: int, failed_rows: [{ line_number: int, error: str }] }

    Requirements: 30.4, 30.5, 30.6
    """
    # Parse the mapping JSON
    try:
        column_mapping: dict[str, str | None] = json.loads(mapping)
    except (json.JSONDecodeError, TypeError) as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mapping JSON: {e}",
        )

    if not column_mapping:
        raise HTTPException(
            status_code=400,
            detail="Column mapping cannot be empty.",
        )

    # Read the uploaded CSV file content
    try:
        content = await file.read()
        text = content.decode("utf-8-sig")  # Handle BOM if present
    except UnicodeDecodeError:
        try:
            text = content.decode("latin-1")
        except Exception:
            raise HTTPException(
                status_code=400,
                detail="Could not decode CSV file. Ensure it is UTF-8 or Latin-1 encoded.",
            )

    # Parse CSV
    reader = csv.DictReader(io.StringIO(text))

    if reader.fieldnames is None:
        raise HTTPException(
            status_code=400,
            detail="CSV file appears to be empty or has no header row.",
        )

    # Validate that mapped CSV columns actually exist in the file
    csv_columns = set(reader.fieldnames)
    for csv_col in column_mapping:
        if csv_col not in csv_columns:
            raise HTTPException(
                status_code=400,
                detail=f"CSV column '{csv_col}' from mapping not found in file headers: {list(csv_columns)}",
            )

    # Build the active mapping (skip null entries)
    active_mapping: dict[str, str] = {
        csv_col: table_col
        for csv_col, table_col in column_mapping.items()
        if table_col is not None
    }

    if not active_mapping:
        raise HTTPException(
            status_code=400,
            detail="All columns in the mapping are set to skip (null). At least one column must be mapped.",
        )

    pool = get_pool()

    async with pool.acquire() as conn:
        # Get column data types for the target table
        col_rows = await conn.fetch(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            """,
            schema,
            table,
        )

        if not col_rows:
            raise HTTPException(
                status_code=404,
                detail=f"Table '{schema}.{table}' not found or has no columns.",
            )

        col_types: dict[str, str] = {row["column_name"]: row["data_type"] for row in col_rows}

        # Validate that all mapped target columns exist in the table
        for csv_col, table_col in active_mapping.items():
            if table_col not in col_types:
                raise HTTPException(
                    status_code=400,
                    detail=f"Target column '{table_col}' (mapped from CSV column '{csv_col}') does not exist in '{schema}.{table}'.",
                )

        # Build the INSERT template
        target_columns = list(active_mapping.values())
        quoted_table = f"{_quote_ident(schema)}.{_quote_ident(table)}"
        quoted_columns = ", ".join(_quote_ident(col) for col in target_columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(target_columns)))
        insert_sql = f"INSERT INTO {quoted_table} ({quoted_columns}) VALUES ({placeholders})"

        # Process rows
        total_rows = 0
        imported_rows = 0
        failed_rows: list[dict[str, Any]] = []

        for row in reader:
            total_rows += 1
            # CSV line number: header is line 1, first data row is line 2
            line_number = total_rows + 1

            try:
                # Build values list by applying the mapping and casting
                values: list[Any] = []
                for csv_col, table_col in active_mapping.items():
                    raw_value = row.get(csv_col)
                    data_type = col_types[table_col]
                    casted = _cast_value(raw_value, data_type)
                    values.append(casted)

                # Execute the insert
                await conn.execute(insert_sql, *values)
                imported_rows += 1

            except asyncpg.UniqueViolationError as e:
                detail = str(e.detail) if e.detail else "Duplicate value"
                failed_rows.append({
                    "line_number": line_number,
                    "error": f"Unique violation: {detail}",
                })
            except asyncpg.ForeignKeyViolationError as e:
                detail = str(e.detail) if e.detail else "Referenced record does not exist"
                failed_rows.append({
                    "line_number": line_number,
                    "error": f"Foreign key violation: {detail}",
                })
            except asyncpg.NotNullViolationError as e:
                column = e.column_name or "unknown"
                failed_rows.append({
                    "line_number": line_number,
                    "error": f"Column '{column}' cannot be null",
                })
            except asyncpg.CheckViolationError as e:
                constraint = e.constraint_name or "unknown"
                failed_rows.append({
                    "line_number": line_number,
                    "error": f"Check constraint '{constraint}' violated",
                })
            except (asyncpg.DataError, asyncpg.InvalidTextRepresentationError) as e:
                failed_rows.append({
                    "line_number": line_number,
                    "error": f"Data type error: {e}",
                })
            except Exception as e:
                failed_rows.append({
                    "line_number": line_number,
                    "error": str(e),
                })

    await AuditLogger.log(
        user_id=user['id'],
        action=f'db_browser_import_csv',
        target_type='database',
        target_id=None,
        details={"schema": schema, "table": table}
    )
    return {
        "total_rows": total_rows,
        "imported_rows": imported_rows,
        "failed_rows": failed_rows,
    }


# ---- Inbox Processing --------------------------------------------------------

# Image extensions for is_image detection
_IMAGE_EXTENSIONS = frozenset([
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".heif", ".avif",
])

# Base paths for inbox and files
_INBOX_DIR = Path("/files/inbox")
_FILES_DIR = Path("/files")
_KNOWLEDGE_DIR = Path("/knowledge")


def _get_smart_capture_url(request: Request) -> str:
    """Resolve the Smart Capture extract URL from app configuration."""
    config = request.app.state.config
    base = config.N8N_BASE.rstrip("/")
    return f"{base}/webhook/smart-capture/extract"


@router.get("/inbox/files")
async def list_inbox_files(
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    List all files in the inbox directory.

    Returns a list of file metadata including name, size, modified timestamp,
    and whether the file is an image (based on extension).

    Requirements: 19.1
    """
    if not _INBOX_DIR.exists():
        return []

    files: list[dict[str, Any]] = []
    for entry in sorted(_INBOX_DIR.iterdir()):
        if not entry.is_file():
            continue
        stat = entry.stat()
        ext = entry.suffix.lower()
        files.append({
            "name": entry.name,
            "size": stat.st_size,
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "is_image": ext in _IMAGE_EXTENSIONS,
        })

    return files


@router.get("/inbox/files/{filename}")
async def serve_inbox_file(
    filename: str,
    user: dict = Depends(require_admin),
):
    """
    Serve a file from the inbox directory for thumbnail display.

    Requirements: 19.1
    """
    # Sanitize filename to prevent directory traversal
    safe_name = Path(filename).name
    file_path = _INBOX_DIR / safe_name

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found in inbox.")

    # Determine MIME type from extension
    ext = file_path.suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif",
        ".webp": "image/webp", ".bmp": "image/bmp",
        ".tiff": "image/tiff", ".tif": "image/tiff",
        ".heic": "image/heic", ".heif": "image/heif",
        ".avif": "image/avif",
        ".pdf": "application/pdf",
    }
    mime = mime_map.get(ext, "application/octet-stream")

    return FileResponse(path=str(file_path), media_type=mime, filename=safe_name)


@router.get("/inbox/tables")
async def list_inbox_tables(
    user: dict = Depends(require_admin),
) -> list[dict[str, Any]]:
    """
    List all tables that have image support (an associated _files link table).

    Uses the same detection logic as the schema sidebar — looks for tables
    with a corresponding `_files` join table in the same schema.

    Requirements: 19.3
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        # Get all tables grouped by schema
        rows = await conn.fetch(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema NOT IN ('pg_catalog', 'pg_toast', 'information_schema')
              AND table_schema NOT LIKE 'pg_%'
            ORDER BY table_schema, table_name
            """
        )

        # Group tables by schema for link table detection
        schema_tables: dict[str, set[str]] = {}
        for row in rows:
            schema_tables.setdefault(row["table_schema"], set()).add(row["table_name"])

        # Find tables that have a corresponding _files link table
        result: list[dict[str, Any]] = []
        for row in rows:
            schema = row["table_schema"]
            table = row["table_name"]
            # Skip the link tables themselves
            if table.endswith("_files"):
                continue
            if _has_link_table(table, schema_tables.get(schema, set())):
                result.append({
                    "schema": schema,
                    "table": table,
                    "full_name": f"{schema}.{table}",
                })

    return result


@router.post("/inbox/process")
async def process_inbox(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Create a row in the target table and link selected photos from the inbox.

    Accepts:
    - table: schema.table format (e.g., "inventory.tools")
    - values: dict of field values to insert
    - photos: list of filenames in the inbox to link

    Steps:
    1. Insert the row into the target table
    2. For each photo: move from /files/inbox/ to /files/inventory/<table>/
    3. Create entries in files.assets
    4. Link via the _files link table

    Requirements: 19.7
    """
    body: dict[str, Any] = await request.json()

    table_ref = body.get("table", "")
    values = body.get("values", {})
    photos: list[str] = body.get("photos", [])

    if not table_ref or "." not in table_ref:
        raise HTTPException(status_code=400, detail="'table' must be in 'schema.table' format.")

    schema, table = table_ref.split(".", 1)

    if not values:
        raise HTTPException(status_code=400, detail="'values' must contain at least one field.")

    pool = get_pool()
    async with pool.acquire() as conn:
        # 1. Insert the row
        columns = list(values.keys())
        vals = list(values.values())
        quoted_table = f"{_quote_ident(schema)}.{_quote_ident(table)}"
        quoted_columns = ", ".join(_quote_ident(col) for col in columns)
        placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))

        insert_sql = (
            f"INSERT INTO {quoted_table} ({quoted_columns}) "
            f"VALUES ({placeholders}) RETURNING *"
        )

        try:
            new_row = await conn.fetchrow(insert_sql, *vals)
        except asyncpg.UniqueViolationError as e:
            detail = str(e.detail) if e.detail else "A record with these values already exists."
            raise HTTPException(status_code=409, detail=f"Duplicate value: {detail}")
        except asyncpg.ForeignKeyViolationError as e:
            detail = str(e.detail) if e.detail else "Referenced record does not exist."
            raise HTTPException(status_code=400, detail=f"Foreign key violation: {detail}")
        except asyncpg.NotNullViolationError as e:
            column = e.column_name or "unknown"
            raise HTTPException(status_code=400, detail=f"Column '{column}' cannot be null.")
        except asyncpg.CheckViolationError as e:
            constraint = e.constraint_name or "unknown"
            raise HTTPException(status_code=400, detail=f"Check constraint '{constraint}' violated.")

        if new_row is None:
            raise HTTPException(status_code=500, detail="Insert succeeded but no row was returned.")

        row_dict = _record_to_dict(new_row)

        # Determine the PK value of the new row
        pk_col = await conn.fetchval(
            """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
                AND tc.table_name = kcu.table_name
            WHERE tc.constraint_type = 'PRIMARY KEY'
              AND tc.table_schema = $1
              AND tc.table_name = $2
            LIMIT 1
            """,
            schema,
            table,
        )
        row_pk = new_row[pk_col] if pk_col else None

        # 2. Link photos if any
        linked_assets: list[str] = []
        if photos and row_pk is not None:
            # Find the link table
            link_info = await _find_link_table(conn, schema, table)
            if link_info is None:
                logger.warning(f"No link table found for {schema}.{table}, skipping photo linking")
            else:
                link_table_name, fk_column = link_info

                # Determine destination directory
                dest_dir = _FILES_DIR / "inventory" / table
                dest_dir.mkdir(parents=True, exist_ok=True)

                for filename in photos:
                    src_path = _INBOX_DIR / filename
                    if not src_path.exists() or not src_path.is_file():
                        logger.warning(f"Inbox file not found: {filename}")
                        continue

                    # Generate asset UUID and determine destination
                    asset_id = uuid.uuid4()
                    ext = src_path.suffix
                    dest_path = dest_dir / f"{asset_id}{ext}"

                    # Move the file
                    shutil.move(str(src_path), str(dest_path))

                    # Compute file metadata
                    stat = dest_path.stat()
                    # Compute sha256
                    sha = hashlib.sha256()
                    with open(dest_path, "rb") as f:
                        for chunk in iter(lambda: f.read(8192), b""):
                            sha.update(chunk)
                    sha256_hex = sha.hexdigest()

                    # Determine mime type from extension
                    mime_map = {
                        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                        ".png": "image/png", ".gif": "image/gif",
                        ".webp": "image/webp", ".bmp": "image/bmp",
                        ".tiff": "image/tiff", ".tif": "image/tiff",
                        ".heic": "image/heic", ".heif": "image/heif",
                        ".avif": "image/avif",
                    }
                    mime = mime_map.get(ext.lower(), "application/octet-stream")

                    # Insert into files.assets (upsert on sha256)
                    await conn.execute(
                        """
                        INSERT INTO files.assets (id, path, original_name, mime, size_bytes, sha256, domain, uploaded_by)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                        ON CONFLICT (sha256) DO NOTHING
                        """,
                        asset_id,
                        str(dest_path),
                        filename,
                        mime,
                        stat.st_size,
                        sha256_hex,
                        table,  # domain = table name
                        user.get("email", "unknown"),
                    )

                    # Link via the _files table
                    link_sql = (
                        f"INSERT INTO {_quote_ident(schema)}.{_quote_ident(link_table_name)} "
                        f"({_quote_ident(fk_column)}, asset_id) VALUES ($1, $2) "
                        f"ON CONFLICT DO NOTHING"
                    )
                    await conn.execute(link_sql, row_pk, asset_id)
                    linked_assets.append(str(asset_id))

    return {
        "ok": True,
        "row": row_dict,
        "linked_assets": linked_assets,
    }


@router.post("/inbox/ai-extract")
async def inbox_ai_extract(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Proxy a request to the Smart Capture extract webhook.

    Accepts:
    - image_path: path to the image (relative to /files, e.g., "inbox/photo.jpg")
    - text: optional text to include in extraction
    - domain_hint: optional domain hint for better extraction

    Returns the Smart Capture extract response (intents, extracted fields).

    Requirements: 19.5
    """
    body: dict[str, Any] = await request.json()

    # Ensure at least image_path or text is provided
    if not body.get("image_path") and not body.get("text"):
        raise HTTPException(
            status_code=400,
            detail="At least one of 'image_path' or 'text' must be provided.",
        )

    # Proxy to Smart Capture extract webhook
    async with get_http_session() as client:
        try:
            url = _get_smart_capture_url(request)
            resp = await client.post(url, json=body, timeout=60.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="Smart Capture extract timed out.")
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"Smart Capture extract failed: {e.response.text[:500]}",
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach Smart Capture service: {e}",
            )


@router.post("/inbox/url-extract")
async def inbox_url_extract(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Proxy a URL extraction request to the Smart Capture extract pipeline.

    Accepts:
    - url: the product/page URL to scrape and extract data from
    - columns: list of target column names to extract values for
    - domain_hint: optional domain hint

    Returns extracted field values from the URL content.

    Requirements: 19.6
    """
    body: dict[str, Any] = await request.json()

    url = body.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="'url' is required.")

    # Build the extraction request — send URL as text with domain_hint
    extract_payload = {
        "text": f"Extract product information from this URL: {url}",
        "domain_hint": body.get("domain_hint"),
    }

    # If columns are provided, include them as context
    columns = body.get("columns")
    if columns:
        extract_payload["text"] += f"\nTarget columns: {', '.join(columns)}"

    async with get_http_session() as client:
        try:
            url_target = _get_smart_capture_url(request)
            resp = await client.post(url_target, json=extract_payload, timeout=60.0)
            resp.raise_for_status()
            return resp.json()
        except httpx.TimeoutException:
            raise HTTPException(status_code=504, detail="URL extraction timed out.")
        except httpx.HTTPStatusError as e:
            raise HTTPException(
                status_code=e.response.status_code,
                detail=f"URL extraction failed: {e.response.text[:500]}",
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=502,
                detail=f"Failed to reach extraction service: {e}",
            )


@router.post("/inbox/knowledge")
async def inbox_knowledge(
    request: Request,
    user: dict = Depends(require_admin),
) -> dict[str, Any]:
    """
    Create a knowledge note and move associated photos.

    Accepts:
    - topic: the knowledge topic (e.g., "woodshop", "cooking/tips")
    - title: the note title
    - notes: the note content (markdown)
    - photos: list of filenames in the inbox to include

    Steps:
    1. Create markdown file at /knowledge/<topic>/<slug>.md
    2. Move photos to /files/knowledge/<slug>/
    3. Register photos in files.assets

    Requirements: 20.3, 20.4
    """
    body: dict[str, Any] = await request.json()

    topic = body.get("topic", "").strip()
    title = body.get("title", "").strip()
    notes = body.get("notes", "").strip()
    photos: list[str] = body.get("photos", [])

    if not topic:
        raise HTTPException(status_code=400, detail="'topic' is required.")
    if not title:
        raise HTTPException(status_code=400, detail="'title' is required.")

    # Generate slug from title
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if not slug:
        slug = str(uuid.uuid4())[:8]

    # Create knowledge directory
    knowledge_dir = _KNOWLEDGE_DIR / topic
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # Build markdown content
    md_lines = [f"# {title}", ""]
    if notes:
        md_lines.append(notes)
        md_lines.append("")

    # Move photos and build image references
    photo_dir = _FILES_DIR / "knowledge" / slug
    registered_assets: list[str] = []

    if photos:
        photo_dir.mkdir(parents=True, exist_ok=True)

        pool = get_pool()
        async with pool.acquire() as conn:
            for filename in photos:
                src_path = _INBOX_DIR / filename
                if not src_path.exists() or not src_path.is_file():
                    logger.warning(f"Inbox file not found for knowledge note: {filename}")
                    continue

                # Generate asset UUID and move
                asset_id = uuid.uuid4()
                ext = src_path.suffix
                dest_path = photo_dir / f"{asset_id}{ext}"

                shutil.move(str(src_path), str(dest_path))

                # Add image reference to markdown
                md_lines.append(f"![{filename}](/files/knowledge/{slug}/{asset_id}{ext})")
                md_lines.append("")

                # Compute metadata
                stat = dest_path.stat()
                sha = hashlib.sha256()
                with open(dest_path, "rb") as f:
                    for chunk in iter(lambda: f.read(8192), b""):
                        sha.update(chunk)
                sha256_hex = sha.hexdigest()

                mime_map = {
                    ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".png": "image/png", ".gif": "image/gif",
                    ".webp": "image/webp", ".bmp": "image/bmp",
                    ".tiff": "image/tiff", ".tif": "image/tiff",
                    ".heic": "image/heic", ".heif": "image/heif",
                    ".avif": "image/avif",
                }
                mime = mime_map.get(ext.lower(), "application/octet-stream")

                # Register in files.assets
                await conn.execute(
                    """
                    INSERT INTO files.assets (id, path, original_name, mime, size_bytes, sha256, domain, uploaded_by)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (sha256) DO NOTHING
                    """,
                    asset_id,
                    str(dest_path),
                    filename,
                    mime,
                    stat.st_size,
                    sha256_hex,
                    "knowledge",
                    user.get("email", "unknown"),
                )
                registered_assets.append(str(asset_id))

    # Write the markdown file
    md_path = knowledge_dir / f"{slug}.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return {
        "ok": True,
        "path": str(md_path),
        "slug": slug,
        "topic": topic,
        "title": title,
        "photos_moved": len(registered_assets),
        "assets": registered_assets,
    }
