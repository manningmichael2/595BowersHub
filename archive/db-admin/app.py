"""
595BowersHub DB Admin — lightweight web UI for viewing/editing Postgres tables.
Runs on port 5002, connects to Postgres via internal Docker network.
Supports image upload via Process Asset pipeline.
"""

import os
import json
import hashlib
import mimetypes
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import httpx
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import asyncpg

app = FastAPI(title="595BowersHub DB Admin")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# --- Database connection pool ------------------------------------------------

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "postgres"),
    "port": int(os.environ.get("DB_PORT", "5432")),
    "database": os.environ.get("DB_NAME", "finance"),
    "user": os.environ.get("DB_USER", "michael"),
    "password": os.environ.get("DB_PASSWORD", ""),
}

# File storage root (bind-mounted from host /home/michael/files)
FILES_ROOT = Path(os.environ.get("FILES_ROOT", "/files"))

# n8n webhook base URL for Process Asset pipeline
N8N_BASE = os.environ.get("N8N_BASE", "http://100.106.180.101:5678")

# Auto-discovered at startup; maps "schema.table" -> (schema, link_table, fk_col)
LINK_TABLES = {}

pool: asyncpg.Pool = None


async def discover_link_tables():
    """Auto-discover *_files link tables by looking for tables with an asset_id FK."""
    global LINK_TABLES
    # Find all _files tables that have a FK to files.assets
    link_tables = await pool.fetch("""
        SELECT tc.table_schema, tc.table_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND ccu.table_schema = 'files'
          AND ccu.table_name = 'assets'
          AND ccu.column_name = 'id'
          AND tc.table_name LIKE '%_files'
    """)

    for r in link_tables:
        link_schema = r["table_schema"]
        link_table = r["table_name"]

        # Find the FK column that is NOT asset_id (i.e., the one pointing to the parent table)
        fk_cols = await pool.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
              AND column_name != 'asset_id'
              AND column_name != 'is_primary'
              AND column_name != 'linked_at'
              AND column_name LIKE '%_id'
        """, link_schema, link_table)

        if not fk_cols:
            continue

        fk_col = fk_cols[0]["column_name"]

        # Derive the parent table: "tool_files" -> "tools", "router_bit_files" -> "router_bits"
        parent_table = link_table.replace("_files", "") + "s"
        # Check if parent table exists
        exists = await pool.fetchval("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = $1 AND table_name = $2
        """, link_schema, parent_table)
        if exists:
            LINK_TABLES[f"{link_schema}.{parent_table}"] = (link_schema, link_table, fk_col)


@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(**DB_CONFIG, min_size=2, max_size=10)
    await discover_link_tables()


@app.on_event("shutdown")
async def shutdown():
    if pool:
        await pool.close()


# --- Helpers -----------------------------------------------------------------


def serialize_value(val):
    """Convert Postgres types to JSON-safe values."""
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, UUID):
        return str(val)
    if isinstance(val, dict):
        return val
    if isinstance(val, list):
        return val
    return val


def serialize_row(record):
    """Convert an asyncpg Record to a plain dict."""
    return {k: serialize_value(v) for k, v in record.items()}


def cast_value(val, data_type):
    """Cast a string value to the appropriate Python type for asyncpg."""
    if val is None:
        return None

    if data_type == 'boolean':
        if isinstance(val, bool):
            return val
        return str(val).lower() in ('true', '1', 'yes', 't')

    if data_type == 'date':
        if isinstance(val, date):
            return val
        # Parse YYYY-MM-DD string
        try:
            return date.fromisoformat(str(val).split('T')[0])
        except (ValueError, AttributeError):
            return None

    if data_type in ('timestamp with time zone', 'timestamp without time zone',
                     'timestamptz', 'timestamp'):
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val))
        except (ValueError, AttributeError):
            return None

    if data_type in ('integer', 'bigint', 'smallint'):
        try:
            return int(val)
        except (ValueError, TypeError):
            return None

    if data_type in ('numeric', 'real', 'double precision'):
        try:
            return Decimal(str(val))
        except Exception:
            return None

    if data_type == 'uuid':
        try:
            return UUID(str(val))
        except (ValueError, AttributeError):
            return None

    # Default: return as string
    return str(val)


# --- API Routes --------------------------------------------------------------


@app.get("/api/schemas")
async def list_schemas():
    """List all non-system schemas."""
    rows = await pool.fetch("""
        SELECT schema_name FROM information_schema.schemata
        WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
        ORDER BY schema_name
    """)
    return [r["schema_name"] for r in rows]


@app.get("/api/tables/{schema}")
async def list_tables(schema: str):
    """List tables in a schema."""
    rows = await pool.fetch("""
        SELECT table_name FROM information_schema.tables
        WHERE table_schema = $1 AND table_type = 'BASE TABLE'
        ORDER BY table_name
    """, schema)
    return [r["table_name"] for r in rows]


@app.get("/api/columns/{schema}/{table}")
async def list_columns(schema: str, table: str):
    """Get column metadata for a table."""
    rows = await pool.fetch("""
        SELECT column_name, data_type, is_nullable, column_default,
               character_maximum_length, numeric_precision, numeric_scale
        FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
        ORDER BY ordinal_position
    """, schema, table)
    return [dict(r) for r in rows]


@app.get("/api/rows/{schema}/{table}")
async def get_rows(schema: str, table: str, limit: int = 100, offset: int = 0,
                   sort: str = None, direction: str = "asc", search: str = None,
                   filters: str = None):
    """Fetch rows from a table with pagination, sorting, search, and column filters.
    filters is a JSON string: [{"col":"brand","op":"eq","val":"Woodline"}, ...]
    Supported ops: eq, neq, like, gt, lt, gte, lte, null, notnull
    """
    # Validate schema/table names to prevent injection
    tables = await pool.fetch("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not tables:
        raise HTTPException(status_code=404, detail="Table not found")

    # Get valid column names for validation
    valid_columns = await pool.fetch("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    valid_col_names = {r["column_name"] for r in valid_columns}

    # Build query
    base = f'SELECT * FROM "{schema}"."{table}"'
    conditions = []
    params = []
    param_idx = 1

    # Text search across all text columns
    if search:
        cols = await pool.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
              AND data_type IN ('text', 'character varying')
        """, schema, table)
        if cols:
            search_conds = []
            for col in cols:
                search_conds.append(f'COALESCE("{col["column_name"]}"::text, \'\') ILIKE ${param_idx}')
                params.append(f"%{search}%")
                param_idx += 1
            conditions.append("(" + " OR ".join(search_conds) + ")")

    # Column-specific filters
    if filters:
        try:
            filter_list = json.loads(filters)
        except (json.JSONDecodeError, TypeError):
            filter_list = []

        for f in filter_list:
            col = f.get("col", "")
            op = f.get("op", "eq")
            val = f.get("val", "")

            if col not in valid_col_names:
                continue

            if op == "null":
                conditions.append(f'"{col}" IS NULL')
            elif op == "notnull":
                conditions.append(f'"{col}" IS NOT NULL')
            elif op == "eq":
                conditions.append(f'"{col}"::text = ${param_idx}')
                params.append(str(val))
                param_idx += 1
            elif op == "neq":
                conditions.append(f'"{col}"::text != ${param_idx}')
                params.append(str(val))
                param_idx += 1
            elif op == "like":
                conditions.append(f'"{col}"::text ILIKE ${param_idx}')
                params.append(f"%{val}%")
                param_idx += 1
            elif op == "gt":
                conditions.append(f'"{col}"::text::numeric > ${param_idx}')
                params.append(str(val))
                param_idx += 1
            elif op == "lt":
                conditions.append(f'"{col}"::text::numeric < ${param_idx}')
                params.append(str(val))
                param_idx += 1
            elif op == "gte":
                conditions.append(f'"{col}"::text::numeric >= ${param_idx}')
                params.append(str(val))
                param_idx += 1
            elif op == "lte":
                conditions.append(f'"{col}"::text::numeric <= ${param_idx}')
                params.append(str(val))
                param_idx += 1

    where_clause = ""
    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    order_clause = ""
    if sort:
        # Validate sort column exists
        valid_cols = await pool.fetch("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2 AND column_name = $3
        """, schema, table, sort)
        if valid_cols:
            dir_sql = "DESC" if direction.lower() == "desc" else "ASC"
            order_clause = f' ORDER BY "{sort}" {dir_sql} NULLS LAST'

    if not order_clause:
        # Default: order by first column
        first_col = await pool.fetchval("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position LIMIT 1
        """, schema, table)
        if first_col:
            order_clause = f' ORDER BY "{first_col}" ASC'

    count_query = f'SELECT COUNT(*) FROM "{schema}"."{table}"{where_clause}'
    total = await pool.fetchval(count_query, *params)

    query = f"{base}{where_clause}{order_clause} LIMIT {limit} OFFSET {offset}"
    rows = await pool.fetch(query, *params)

    return {
        "rows": [serialize_row(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.get("/api/pk/{schema}/{table}")
async def get_primary_key(schema: str, table: str):
    """Get primary key column(s) for a table."""
    rows = await pool.fetch("""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.indisprimary AND c.relname = $1 AND n.nspname = $2
    """, table, schema)
    return [r["attname"] for r in rows]


@app.put("/api/rows/{schema}/{table}")
async def update_row(schema: str, table: str, request: Request):
    """Update a row. Body: {pk: {col: val}, updates: {col: val}}"""
    body = await request.json()
    pk = body.get("pk", {})
    updates = body.get("updates", {})

    if not pk or not updates:
        raise HTTPException(status_code=400, detail="pk and updates required")

    # Validate table exists
    tables = await pool.fetch("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not tables:
        raise HTTPException(status_code=404, detail="Table not found")

    # Build UPDATE
    set_parts = []
    where_parts = []
    params = []
    idx = 1

    # Get column types for proper casting
    col_types = {}
    col_rows = await pool.fetch("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    for r in col_rows:
        col_types[r["column_name"]] = r["data_type"]

    for col, val in updates.items():
        set_parts.append(f'"{col}" = ${idx}')
        params.append(cast_value(val, col_types.get(col, 'text')))
        idx += 1

    for col, val in pk.items():
        where_parts.append(f'"{col}" = ${idx}')
        params.append(val)
        idx += 1

    # Auto-update updated_at if the column exists
    has_updated_at = await pool.fetchval("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2 AND column_name = 'updated_at'
    """, schema, table)
    if has_updated_at and "updated_at" not in updates:
        set_parts.append('"updated_at" = now()')

    query = f'UPDATE "{schema}"."{table}" SET {", ".join(set_parts)} WHERE {" AND ".join(where_parts)}'
    result = await pool.execute(query, *params)

    return {"ok": True, "result": result}


@app.post("/api/rows/{schema}/{table}/archive")
async def archive_row(schema: str, table: str, request: Request):
    """Soft-delete: set archived_at = now(). Body: {pk: {col: val}}"""
    body = await request.json()
    pk = body.get("pk", {})

    if not pk:
        raise HTTPException(status_code=400, detail="pk required")

    # Check archived_at column exists
    has_col = await pool.fetchval("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2 AND column_name = 'archived_at'
    """, schema, table)
    if not has_col:
        raise HTTPException(status_code=400, detail="Table does not support archiving (no archived_at column)")

    where_parts = []
    params = []
    idx = 1
    for col, val in pk.items():
        where_parts.append(f'"{col}" = ${idx}')
        params.append(val)
        idx += 1

    query = f'UPDATE "{schema}"."{table}" SET "archived_at" = now() WHERE {" AND ".join(where_parts)}'
    await pool.execute(query, *params)
    return {"ok": True, "action": "archived"}


@app.post("/api/rows/{schema}/{table}/delete")
async def delete_row(schema: str, table: str, request: Request):
    """Hard delete a row. Body: {pk: {col: val}}"""
    body = await request.json()
    pk = body.get("pk", {})

    if not pk:
        raise HTTPException(status_code=400, detail="pk required")

    tables = await pool.fetch("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not tables:
        raise HTTPException(status_code=404, detail="Table not found")

    where_parts = []
    params = []
    idx = 1
    for col, val in pk.items():
        where_parts.append(f'"{col}" = ${idx}')
        params.append(val)
        idx += 1

    query = f'DELETE FROM "{schema}"."{table}" WHERE {" AND ".join(where_parts)}'
    await pool.execute(query, *params)
    return {"ok": True, "action": "deleted"}


@app.post("/api/rows/{schema}/{table}/insert")
async def insert_row(schema: str, table: str, request: Request):
    """Insert a new row. Body: {values: {col: val}}"""
    body = await request.json()
    values = body.get("values", {})

    if not values:
        raise HTTPException(status_code=400, detail="values required")

    tables = await pool.fetch("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not tables:
        raise HTTPException(status_code=404, detail="Table not found")

    # Get column types for proper casting
    col_types = {}
    col_rows = await pool.fetch("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    for r in col_rows:
        col_types[r["column_name"]] = r["data_type"]

    cols = []
    placeholders = []
    params = []
    idx = 1
    for col, val in values.items():
        cols.append(f'"{col}"')
        placeholders.append(f"${idx}")
        params.append(cast_value(val, col_types.get(col, 'text')))
        idx += 1

    query = f'INSERT INTO "{schema}"."{table}" ({", ".join(cols)}) VALUES ({", ".join(placeholders)}) RETURNING *'
    try:
        row = await pool.fetchrow(query, *params)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True, "row": serialize_row(row) if row else None}


# --- Table Creation -----------------------------------------------------------

ALLOWED_SCHEMAS = ['inventory', 'cook', 'house']

COLUMN_TYPE_MAP = {
    'text': 'TEXT',
    'number': 'NUMERIC',
    'integer': 'BIGINT',
    'decimal': 'NUMERIC(10,2)',
    'boolean': 'BOOLEAN',
    'date': 'DATE',
    'timestamp': 'TIMESTAMPTZ',
}


@app.post("/api/create-table")
async def create_table(request: Request):
    """
    Create a new table with standard columns.
    Body: {
        schema: "inventory",
        table_name: "clamps",
        columns: [{name: "brand", type: "text", nullable: true}, ...],
        create_files_table: true
    }
    Returns: {ok, sql_executed, table, files_table}
    """
    body = await request.json()
    schema = body.get("schema", "").strip().lower()
    table_name = body.get("table_name", "").strip().lower()
    columns = body.get("columns", [])
    create_files = body.get("create_files_table", True)

    # Validation
    if schema not in ALLOWED_SCHEMAS:
        raise HTTPException(status_code=400,
                            detail=f"Schema must be one of: {', '.join(ALLOWED_SCHEMAS)}")

    if not table_name or not table_name.replace('_', '').isalnum():
        raise HTTPException(status_code=400,
                            detail="Table name must be alphanumeric with underscores only")

    if len(table_name) > 63:
        raise HTTPException(status_code=400, detail="Table name too long (max 63 chars)")

    # Check table doesn't already exist
    existing = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table_name)
    if existing:
        raise HTTPException(status_code=409,
                            detail=f"Table {schema}.{table_name} already exists")

    if not columns:
        raise HTTPException(status_code=400, detail="At least one column required")

    # Build column definitions
    col_defs = []
    for col in columns:
        col_name = col.get("name", "").strip().lower().replace(' ', '_')
        col_type = col.get("type", "text").lower()
        nullable = col.get("nullable", True)

        if not col_name or not col_name.replace('_', '').isalnum():
            raise HTTPException(status_code=400,
                                detail=f"Invalid column name: {col.get('name')}")

        pg_type = COLUMN_TYPE_MAP.get(col_type, 'TEXT')
        null_str = "" if nullable else " NOT NULL"
        col_defs.append(f'    "{col_name}" {pg_type}{null_str}')

    # Build CREATE TABLE SQL
    all_cols = [
        '    id BIGSERIAL PRIMARY KEY',
        *col_defs,
        '    notes TEXT',
        '    created_at TIMESTAMPTZ NOT NULL DEFAULT now()',
        '    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()',
        '    archived_at TIMESTAMPTZ',
    ]

    cols_joined = ",\n".join(all_cols)
    create_sql = f'CREATE TABLE "{schema}"."{table_name}" (\n{cols_joined}\n);'

    # Build _files link table SQL
    files_sql = ""
    if create_files:
        singular = table_name.rstrip('s')  # naive singularize
        fk_col = f"{singular}_id"
        files_table = f"{singular}_files"

        files_sql = f"""
CREATE TABLE "{schema}"."{files_table}" (
    "{fk_col}" BIGINT NOT NULL REFERENCES "{schema}"."{table_name}"(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES files.assets(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY ("{fk_col}", asset_id)
);
CREATE INDEX ON "{schema}"."{files_table}" (asset_id);"""

    # Execute
    full_sql = create_sql + "\n" + files_sql
    try:
        await pool.execute(full_sql)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SQL error: {str(e)}")

    # Grant read access to finance_reader if it exists
    try:
        has_reader = await pool.fetchval(
            "SELECT 1 FROM pg_roles WHERE rolname = 'finance_reader'"
        )
        if has_reader:
            await pool.execute(f'GRANT SELECT ON "{schema}"."{table_name}" TO finance_reader')
            if create_files:
                await pool.execute(
                    f'GRANT SELECT ON "{schema}"."{files_table}" TO finance_reader'
                )
    except Exception:
        pass  # Non-critical

    # Register in LINK_TABLES for image support (runtime only — persists until restart)
    if create_files:
        LINK_TABLES[f"{schema}.{table_name}"] = (schema, files_table, fk_col)

    return {
        "ok": True,
        "sql_executed": full_sql,
        "table": f"{schema}.{table_name}",
        "files_table": f"{schema}.{files_table}" if create_files else None,
    }


@app.post("/api/preview-create-table")
async def preview_create_table(request: Request):
    """Preview the SQL that would be generated without executing it."""
    body = await request.json()
    schema = body.get("schema", "").strip().lower()
    table_name = body.get("table_name", "").strip().lower()
    columns = body.get("columns", [])
    create_files = body.get("create_files_table", True)

    if schema not in ALLOWED_SCHEMAS:
        raise HTTPException(status_code=400,
                            detail=f"Schema must be one of: {', '.join(ALLOWED_SCHEMAS)}")

    if not table_name:
        raise HTTPException(status_code=400, detail="Table name required")

    col_defs = []
    for col in columns:
        col_name = col.get("name", "").strip().lower().replace(' ', '_')
        col_type = col.get("type", "text").lower()
        nullable = col.get("nullable", True)
        pg_type = COLUMN_TYPE_MAP.get(col_type, 'TEXT')
        null_str = "" if nullable else " NOT NULL"
        col_defs.append(f'    "{col_name}" {pg_type}{null_str}')

    all_cols = [
        '    id BIGSERIAL PRIMARY KEY',
        *col_defs,
        '    notes TEXT',
        '    created_at TIMESTAMPTZ NOT NULL DEFAULT now()',
        '    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()',
        '    archived_at TIMESTAMPTZ',
    ]

    cols_joined = ",\n".join(all_cols)
    create_sql = f'CREATE TABLE "{schema}"."{table_name}" (\n{cols_joined}\n);'

    files_sql = ""
    if create_files:
        singular = table_name.rstrip('s')
        fk_col = f"{singular}_id"
        files_table = f"{singular}_files"
        files_sql = f"""
CREATE TABLE "{schema}"."{files_table}" (
    "{fk_col}" BIGINT NOT NULL REFERENCES "{schema}"."{table_name}"(id) ON DELETE CASCADE,
    asset_id UUID NOT NULL REFERENCES files.assets(id) ON DELETE CASCADE,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    linked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY ("{fk_col}", asset_id)
);
CREATE INDEX ON "{schema}"."{files_table}" (asset_id);"""

    return {"sql": create_sql + "\n" + files_sql}


# --- Schema Management -------------------------------------------------------


@app.post("/api/create-schema")
async def create_schema(request: Request):
    """Create a new schema. Body: {name: "woodshop"}"""
    body = await request.json()
    name = body.get("name", "").strip().lower()

    if not name or not name.replace('_', '').isalnum():
        raise HTTPException(status_code=400, detail="Schema name must be alphanumeric with underscores")
    if len(name) > 63:
        raise HTTPException(status_code=400, detail="Schema name too long")

    # Don't allow system schemas
    if name in ('pg_catalog', 'information_schema', 'pg_toast', 'public'):
        raise HTTPException(status_code=400, detail=f"Cannot create schema '{name}'")

    try:
        await pool.execute(f'CREATE SCHEMA IF NOT EXISTS "{name}"')
        # Grant read to finance_reader if exists
        has_reader = await pool.fetchval("SELECT 1 FROM pg_roles WHERE rolname = 'finance_reader'")
        if has_reader:
            await pool.execute(f'GRANT USAGE ON SCHEMA "{name}" TO finance_reader')
            await pool.execute(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{name}" TO finance_reader')
            await pool.execute(f'ALTER DEFAULT PRIVILEGES IN SCHEMA "{name}" GRANT SELECT ON TABLES TO finance_reader')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "schema": name}


@app.post("/api/move-table")
async def move_table(request: Request):
    """Move a table to a different schema. Body: {schema, table, new_schema}"""
    body = await request.json()
    schema = body.get("schema", "").strip()
    table = body.get("table", "").strip()
    new_schema = body.get("new_schema", "").strip()

    if not schema or not table or not new_schema:
        raise HTTPException(status_code=400, detail="schema, table, and new_schema required")

    # Verify source table exists
    exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not exists:
        raise HTTPException(status_code=404, detail=f"Table {schema}.{table} not found")

    # Verify target schema exists
    schema_exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.schemata WHERE schema_name = $1
    """, new_schema)
    if not schema_exists:
        raise HTTPException(status_code=404, detail=f"Schema '{new_schema}' does not exist")

    # Check no name collision
    collision = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, new_schema, table)
    if collision:
        raise HTTPException(status_code=409, detail=f"Table {new_schema}.{table} already exists")

    try:
        await pool.execute(f'ALTER TABLE "{schema}"."{table}" SET SCHEMA "{new_schema}"')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Re-discover link tables since paths changed
    await discover_link_tables()

    return {"ok": True, "moved": f"{schema}.{table} → {new_schema}.{table}"}


@app.post("/api/add-column")
async def add_column(request: Request):
    """Add a column to an existing table. Body: {schema, table, name, type, nullable}"""
    body = await request.json()
    schema = body.get("schema", "").strip()
    table = body.get("table", "").strip()
    col_name = body.get("name", "").strip().lower().replace(' ', '_')
    col_type = body.get("type", "text").lower()
    nullable = body.get("nullable", True)

    if not schema or not table or not col_name:
        raise HTTPException(status_code=400, detail="schema, table, and name required")

    if not col_name.replace('_', '').isalnum():
        raise HTTPException(status_code=400, detail="Column name must be alphanumeric with underscores")

    # Verify table exists
    exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not exists:
        raise HTTPException(status_code=404, detail=f"Table {schema}.{table} not found")

    pg_type = COLUMN_TYPE_MAP.get(col_type, 'TEXT')
    null_str = "" if nullable else " NOT NULL"

    try:
        await pool.execute(f'ALTER TABLE "{schema}"."{table}" ADD COLUMN IF NOT EXISTS "{col_name}" {pg_type}{null_str}')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "column": f"{schema}.{table}.{col_name}", "type": pg_type}


@app.post("/api/rename-table")
async def rename_table(request: Request):
    """Rename a table. Body: {schema, table, new_name}"""
    body = await request.json()
    schema = body.get("schema", "").strip()
    table = body.get("table", "").strip()
    new_name = body.get("new_name", "").strip().lower()

    if not schema or not table or not new_name:
        raise HTTPException(status_code=400, detail="schema, table, and new_name required")

    if not new_name.replace('_', '').isalnum():
        raise HTTPException(status_code=400, detail="Table name must be alphanumeric with underscores")

    exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not exists:
        raise HTTPException(status_code=404, detail=f"Table {schema}.{table} not found")

    try:
        await pool.execute(f'ALTER TABLE "{schema}"."{table}" RENAME TO "{new_name}"')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    await discover_link_tables()
    return {"ok": True, "renamed": f"{schema}.{table} → {schema}.{new_name}"}


@app.post("/api/drop-column")
async def drop_column(request: Request):
    """Drop a column from a table. Body: {schema, table, column}"""
    body = await request.json()
    schema = body.get("schema", "").strip()
    table = body.get("table", "").strip()
    column = body.get("column", "").strip()

    if not schema or not table or not column:
        raise HTTPException(status_code=400, detail="schema, table, and column required")

    # Don't allow dropping PK or critical columns
    is_pk = await pool.fetchval("""
        SELECT 1 FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.indisprimary AND c.relname = $1 AND n.nspname = $2 AND a.attname = $3
    """, table, schema, column)
    if is_pk:
        raise HTTPException(status_code=400, detail="Cannot drop primary key column")

    # Verify column exists
    exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2 AND column_name = $3
    """, schema, table, column)
    if not exists:
        raise HTTPException(status_code=404, detail=f"Column {column} not found")

    try:
        await pool.execute(f'ALTER TABLE "{schema}"."{table}" DROP COLUMN "{column}"')
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "dropped": f"{schema}.{table}.{column}"}


# --- Relationships / Lookup Columns ------------------------------------------


@app.get("/api/relationships/{schema}/{table}")
async def get_relationships(schema: str, table: str):
    """Get all foreign key relationships for a table (both outgoing and incoming)."""
    # Outgoing: columns in this table that reference other tables
    outgoing = await pool.fetch("""
        SELECT
            kcu.column_name AS fk_column,
            ccu.table_schema AS ref_schema,
            ccu.table_name AS ref_table,
            ccu.column_name AS ref_column
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
            ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON tc.constraint_name = ccu.constraint_name
        WHERE tc.constraint_type = 'FOREIGN KEY'
          AND tc.table_schema = $1 AND tc.table_name = $2
    """, schema, table)

    return {
        "outgoing": [dict(r) for r in outgoing],
    }


@app.get("/api/lookup-options/{schema}/{table}")
async def get_lookup_options(schema: str, table: str, limit: int = 200):
    """Get rows from a table formatted as lookup options (id + display label)."""
    # Find the best display column (name, title, profile, or first text column)
    display_col = await pool.fetchval("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
          AND column_name IN ('name', 'title', 'profile', 'brand', 'description')
        ORDER BY
            CASE column_name
                WHEN 'name' THEN 1
                WHEN 'title' THEN 2
                WHEN 'profile' THEN 3
                WHEN 'brand' THEN 4
                WHEN 'description' THEN 5
            END
        LIMIT 1
    """, schema, table)

    if not display_col:
        # Fallback: first text column that isn't 'id'
        display_col = await pool.fetchval("""
            SELECT column_name FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
              AND data_type IN ('text', 'character varying')
              AND column_name != 'id'
            ORDER BY ordinal_position LIMIT 1
        """, schema, table)

    if not display_col:
        display_col = 'id'

    # Get the PK column
    pk_col = await pool.fetchval("""
        SELECT a.attname
        FROM pg_index i
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class c ON c.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE i.indisprimary AND c.relname = $1 AND n.nspname = $2
        LIMIT 1
    """, table, schema)

    if not pk_col:
        pk_col = 'id'

    rows = await pool.fetch(f"""
        SELECT "{pk_col}" AS id, "{display_col}" AS label
        FROM "{schema}"."{table}"
        WHERE archived_at IS NULL OR archived_at IS NULL
        ORDER BY "{display_col}" ASC NULLS LAST
        LIMIT {limit}
    """)

    return {
        "pk_col": pk_col,
        "display_col": display_col,
        "options": [{"id": serialize_value(r["id"]), "label": serialize_value(r["label"])} for r in rows],
    }


@app.post("/api/add-lookup-column")
async def add_lookup_column(request: Request):
    """Add a foreign key (lookup) column. Body: {schema, table, name, ref_schema, ref_table}"""
    body = await request.json()
    schema = body.get("schema", "").strip()
    table = body.get("table", "").strip()
    col_name = body.get("name", "").strip().lower().replace(' ', '_')
    ref_schema = body.get("ref_schema", "").strip()
    ref_table = body.get("ref_table", "").strip()

    if not all([schema, table, col_name, ref_schema, ref_table]):
        raise HTTPException(status_code=400, detail="All fields required: schema, table, name, ref_schema, ref_table")

    # Verify source table
    exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not exists:
        raise HTTPException(status_code=404, detail=f"Table {schema}.{table} not found")

    # Verify target table
    ref_exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables WHERE table_schema = $1 AND table_name = $2
    """, ref_schema, ref_table)
    if not ref_exists:
        raise HTTPException(status_code=404, detail=f"Referenced table {ref_schema}.{ref_table} not found")

    # Get PK type of referenced table
    pk_type = await pool.fetchval("""
        SELECT data_type FROM information_schema.columns c
        JOIN pg_index i ON true
        JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        JOIN pg_class cl ON cl.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = cl.relnamespace
        WHERE i.indisprimary AND cl.relname = $1 AND n.nspname = $2
          AND c.table_schema = $2 AND c.table_name = $1 AND c.column_name = a.attname
        LIMIT 1
    """, ref_table, ref_schema)

    pg_col_type = 'BIGINT'  # Default for serial PKs
    if pk_type and 'uuid' in pk_type.lower():
        pg_col_type = 'UUID'

    # Ensure column name ends with _id for clarity
    if not col_name.endswith('_id'):
        col_name = col_name + '_id'

    try:
        await pool.execute(f"""
            ALTER TABLE "{schema}"."{table}"
            ADD COLUMN IF NOT EXISTS "{col_name}" {pg_col_type}
            REFERENCES "{ref_schema}"."{ref_table}"(id) ON DELETE SET NULL
        """)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"ok": True, "column": col_name, "references": f"{ref_schema}.{ref_table}"}


# --- Image/File Routes -------------------------------------------------------


def get_link_table_info(schema: str, table: str):
    """Get the link table info for a domain table, or None."""
    key = f"{schema}.{table}"
    return LINK_TABLES.get(key)


@app.get("/api/images/{schema}/{table}/{row_id}")
async def get_row_images(schema: str, table: str, row_id: str):
    """Get all images linked to a row via its _files link table."""
    link_info = get_link_table_info(schema, table)
    if not link_info:
        return []

    link_schema, link_table, fk_col = link_info

    query = f"""
        SELECT a.id, a.path, a.original_name, a.mime, a.ai_summary, a.uploaded_at,
               lf.is_primary
        FROM "{link_schema}"."{link_table}" lf
        JOIN files.assets a ON a.id = lf.asset_id
        WHERE lf."{fk_col}" = $1
        ORDER BY lf.is_primary DESC, a.uploaded_at DESC
    """

    # Try to cast row_id to appropriate type
    try:
        pk_val = int(row_id)
    except ValueError:
        pk_val = row_id

    rows = await pool.fetch(query, pk_val)
    return [serialize_row(r) for r in rows]


@app.get("/files/{path:path}")
async def serve_file(path: str):
    """Serve a file from the files directory."""
    file_path = FILES_ROOT / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # Security: ensure path doesn't escape FILES_ROOT
    try:
        file_path.resolve().relative_to(FILES_ROOT.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(file_path)


@app.post("/api/upload/{schema}/{table}/{row_id}")
async def upload_image(schema: str, table: str, row_id: str,
                       file: UploadFile = File(...)):
    """Upload an image, save to inbox, link to the row."""
    link_info = get_link_table_info(schema, table)
    if not link_info:
        raise HTTPException(status_code=400,
                            detail=f"Table {schema}.{table} does not support image attachments")

    link_schema, link_table, fk_col = link_info

    # Save file to inbox
    inbox = FILES_ROOT / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Use original filename
    filename = file.filename or "upload.jpg"
    dest = inbox / filename

    # Avoid overwriting — append counter if exists
    counter = 1
    stem = dest.stem
    suffix = dest.suffix
    while dest.exists():
        dest = inbox / f"{stem}_{counter}{suffix}"
        counter += 1

    dest.write_bytes(content)

    # Determine domain hint from schema/table
    domain_hints = {
        "inventory.tools": "tool",
        "inventory.router_bits": "tool",
        "inventory.saw_blades": "saw_blade",
        "inventory.wood": "wood",
        "inventory.albums": "album",
        "inventory.manuals": "manual",
        "house.rooms": "house_room",
        "cook.recipes": "cook_recipe",
    }
    domain_hint = domain_hints.get(f"{schema}.{table}", None)

    # Call Process Asset webhook
    relative_path = f"inbox/{dest.name}"
    asset_id = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{N8N_BASE}/webhook/process-asset", json={
                "path": relative_path,
                "domain_hint": domain_hint,
                "uploaded_by": "db-admin",
                "original_name": filename,
            })
            if resp.status_code == 200:
                data = resp.json()
                asset_id = data.get("asset_id")
    except Exception as e:
        # Process Asset failed — still save the file, just insert asset row manually
        pass

    if not asset_id:
        # Fallback: insert into files.assets directly
        sha = hashlib.sha256(content).hexdigest()
        mime_type = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        # Check for existing asset with same sha256
        existing = await pool.fetchval(
            "SELECT id FROM files.assets WHERE sha256 = $1", sha
        )
        if existing:
            asset_id = str(existing)
            # Clean up the duplicate file
            dest.unlink(missing_ok=True)
        else:
            row = await pool.fetchrow("""
                INSERT INTO files.assets (path, original_name, mime, size_bytes, sha256, domain, uploaded_by)
                VALUES ($1, $2, $3, $4, $5, $6, 'db-admin')
                RETURNING id
            """, str(dest), filename, mime_type, len(content), sha, domain_hint)
            asset_id = str(row["id"])

    # Link asset to the row
    if asset_id:
        try:
            pk_val = int(row_id)
        except ValueError:
            pk_val = row_id

        # Check if link already exists
        existing_link = await pool.fetchval(f"""
            SELECT 1 FROM "{link_schema}"."{link_table}"
            WHERE "{fk_col}" = $1 AND asset_id = $2
        """, pk_val, UUID(asset_id) if isinstance(asset_id, str) else asset_id)

        if not existing_link:
            # Check if this is the first image (make it primary)
            count = await pool.fetchval(f"""
                SELECT COUNT(*) FROM "{link_schema}"."{link_table}" WHERE "{fk_col}" = $1
            """, pk_val)
            is_primary = (count == 0)

            await pool.execute(f"""
                INSERT INTO "{link_schema}"."{link_table}" ("{fk_col}", asset_id, is_primary)
                VALUES ($1, $2, $3)
            """, pk_val, UUID(asset_id) if isinstance(asset_id, str) else asset_id, is_primary)

    return {"ok": True, "asset_id": asset_id}


@app.get("/api/thumbnails/{schema}/{table}")
async def get_thumbnails(schema: str, table: str):
    """Get primary image paths for all rows in a table (for list view icons)."""
    link_info = get_link_table_info(schema, table)
    if not link_info:
        return {}

    link_schema, link_table, fk_col = link_info

    rows = await pool.fetch(f"""
        SELECT lf."{fk_col}" AS row_id, a.path
        FROM "{link_schema}"."{link_table}" lf
        JOIN files.assets a ON a.id = lf.asset_id
        WHERE lf.is_primary = true
    """)

    result = {}
    for r in rows:
        path = r["path"]
        # Normalize path for serving
        path = path.replace("/home/michael/files/", "").replace("/files/", "")
        result[str(r["row_id"])] = f"/files/{path}"

    return result


@app.post("/api/reorder-images/{schema}/{table}/{row_id}")
async def reorder_images(schema: str, table: str, row_id: str, request: Request):
    """Reorder images and set primary. Body: {asset_ids: ["uuid1", "uuid2", ...]}
    First in the list becomes primary."""
    body = await request.json()
    asset_ids = body.get("asset_ids", [])

    if not asset_ids:
        raise HTTPException(status_code=400, detail="asset_ids required")

    link_info = get_link_table_info(schema, table)
    if not link_info:
        raise HTTPException(status_code=400, detail="Table does not support images")

    link_schema, link_table, fk_col = link_info

    try:
        pk_val = int(row_id)
    except ValueError:
        pk_val = row_id

    # Set all to non-primary first
    await pool.execute(f"""
        UPDATE "{link_schema}"."{link_table}"
        SET is_primary = false
        WHERE "{fk_col}" = $1
    """, pk_val)

    # Set the first one as primary
    if asset_ids:
        await pool.execute(f"""
            UPDATE "{link_schema}"."{link_table}"
            SET is_primary = true
            WHERE "{fk_col}" = $1 AND asset_id = $2
        """, pk_val, UUID(asset_ids[0]))

    return {"ok": True, "primary": asset_ids[0] if asset_ids else None}


@app.post("/api/unlink-image/{schema}/{table}/{row_id}/{asset_id}")
async def unlink_image(schema: str, table: str, row_id: str, asset_id: str):
    """Remove an image link from a row (does not delete the file)."""
    link_info = get_link_table_info(schema, table)
    if not link_info:
        raise HTTPException(status_code=400, detail="Table does not support images")

    link_schema, link_table, fk_col = link_info

    try:
        pk_val = int(row_id)
    except ValueError:
        pk_val = row_id

    await pool.execute(f"""
        DELETE FROM "{link_schema}"."{link_table}"
        WHERE "{fk_col}" = $1 AND asset_id = $2
    """, pk_val, UUID(asset_id))

    # If we deleted the primary, promote the next one
    remaining = await pool.fetchval(f"""
        SELECT COUNT(*) FROM "{link_schema}"."{link_table}"
        WHERE "{fk_col}" = $1 AND is_primary = true
    """, pk_val)

    if remaining == 0:
        # No primary — set the first remaining image as primary
        await pool.execute(f"""
            UPDATE "{link_schema}"."{link_table}"
            SET is_primary = true
            WHERE "{fk_col}" = $1
              AND asset_id = (
                  SELECT asset_id FROM "{link_schema}"."{link_table}"
                  WHERE "{fk_col}" = $1 ORDER BY linked_at LIMIT 1
              )
        """, pk_val)

    return {"ok": True, "unlinked": asset_id}


# --- Field Hints Settings -----------------------------------------------------


@app.get("/api/field-hints")
async def get_field_hints():
    """Get all saved field hints from the database."""
    rows = await pool.fetch("""
        SELECT column_name, hint_type, options, prefix, suffix,
               min_val, max_val, step_val, placeholder
        FROM public.db_admin_field_hints
        ORDER BY column_name
    """)
    hints = {}
    for r in rows:
        hint = {"type": r["hint_type"]}
        if r["options"]:
            hint["options"] = json.loads(r["options"]) if isinstance(r["options"], str) else r["options"]
        if r["prefix"]:
            hint["prefix"] = r["prefix"]
        if r["suffix"]:
            hint["suffix"] = r["suffix"]
        if r["min_val"] is not None:
            hint["min"] = float(r["min_val"])
        if r["max_val"] is not None:
            hint["max"] = float(r["max_val"])
        if r["step_val"] is not None:
            hint["step"] = float(r["step_val"])
        if r["placeholder"]:
            hint["placeholder"] = r["placeholder"]
        hints[r["column_name"]] = hint
    return hints


@app.put("/api/field-hints/{column_name}")
async def save_field_hint(column_name: str, request: Request):
    """Save or update a field hint. Body: {type, options?, prefix?, suffix?, min?, max?, step?, placeholder?}"""
    body = await request.json()
    hint_type = body.get("type", "text").strip().lower()
    options = body.get("options")
    prefix = body.get("prefix", "").strip() or None
    suffix = body.get("suffix", "").strip() or None
    min_val = body.get("min")
    max_val = body.get("max")
    step_val = body.get("step")
    placeholder = body.get("placeholder", "").strip() or None

    # Validate type
    valid_types = ["text", "number", "fraction", "select", "url", "date", "boolean"]
    if hint_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"type must be one of: {', '.join(valid_types)}")

    # Convert options to JSON
    options_json = json.dumps(options) if options else None

    await pool.execute("""
        INSERT INTO public.db_admin_field_hints
            (column_name, hint_type, options, prefix, suffix, min_val, max_val, step_val, placeholder, updated_at)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9, now())
        ON CONFLICT (column_name) DO UPDATE SET
            hint_type = EXCLUDED.hint_type,
            options = EXCLUDED.options,
            prefix = EXCLUDED.prefix,
            suffix = EXCLUDED.suffix,
            min_val = EXCLUDED.min_val,
            max_val = EXCLUDED.max_val,
            step_val = EXCLUDED.step_val,
            placeholder = EXCLUDED.placeholder,
            updated_at = now()
    """, column_name, hint_type, options_json,
        prefix, suffix,
        Decimal(str(min_val)) if min_val is not None else None,
        Decimal(str(max_val)) if max_val is not None else None,
        Decimal(str(step_val)) if step_val is not None else None,
        placeholder)

    return {"ok": True, "column_name": column_name, "type": hint_type}


@app.delete("/api/field-hints/{column_name}")
async def delete_field_hint(column_name: str):
    """Delete a field hint (reverts to hardcoded default or auto-detection)."""
    await pool.execute(
        "DELETE FROM public.db_admin_field_hints WHERE column_name = $1",
        column_name
    )
    return {"ok": True, "deleted": column_name}


@app.get("/api/all-columns")
async def get_all_columns():
    """Get all column names across all user tables, grouped by table."""
    rows = await pool.fetch("""
        SELECT table_schema, table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema IN ('public', 'inventory', 'files', 'house', 'cook')
          AND table_name NOT LIKE 'pg_%'
        ORDER BY column_name, table_schema, table_name
    """)
    # Group by column_name
    columns = {}
    for r in rows:
        col = r["column_name"]
        if col not in columns:
            columns[col] = {"data_type": r["data_type"], "tables": []}
        columns[col]["tables"].append(f"{r['table_schema']}.{r['table_name']}")
    return columns


@app.get("/api/inbox-files")
async def list_inbox_files():
    """List files in /files/inbox/ with thumbnails."""
    inbox = FILES_ROOT / "inbox"
    if not inbox.exists():
        return {"ok": True, "files": []}
    files = []
    for f in sorted(inbox.iterdir()):
        if f.is_file() and not f.name.startswith('.'):
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            files.append({
                "name": f.name,
                "size_bytes": f.stat().st_size,
                "mime": mime,
                "is_image": mime.startswith("image/"),
                "path": f"inbox/{f.name}",
            })
    return {"ok": True, "files": files}


@app.get("/api/tables-with-images")
async def tables_with_images():
    """List all tables that support image attachments (have _files link tables)."""
    return [{"schema": k.split('.')[0], "table": k.split('.')[1]} for k in LINK_TABLES.keys()]


@app.post("/api/ai-extract")
async def ai_extract(request: Request):
    """Proxy to Smart Capture extract webhook."""
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{N8N_BASE}/webhook/smart-capture/extract",
                json=body
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/api/ai-commit")
async def ai_commit(request: Request):
    """Proxy to Smart Capture commit webhook."""
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{N8N_BASE}/webhook/smart-capture/commit",
                json=body
            )
            return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.post("/api/scrape-product")
async def scrape_product(request: Request):
    """Scrape a product URL and extract structured fields using AI via n8n.
    Body: {url: "https://...", table: "tools"}
    Returns: {ok, fields: {brand: "DeWalt", model: "DW735", ...}}
    """
    body = await request.json()
    url = body.get("url", "").strip()
    table = body.get("table", "tools")

    if not url:
        raise HTTPException(status_code=400, detail="url required")

    # Fetch the page content
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; 595BowersHub/1.0)"
            })
            if resp.status_code != 200:
                return {"ok": False, "error": f"HTTP {resp.status_code} fetching URL"}
            page_text = resp.text[:10000]  # Limit to first 10K chars
    except Exception as e:
        return {"ok": False, "error": f"Failed to fetch URL: {str(e)}"}

    # Get columns for the target table
    cols = await pool.fetch("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = 'inventory' AND table_name = $1
          AND column_name NOT IN ('id', 'created_at', 'updated_at', 'archived_at')
        ORDER BY ordinal_position
    """, table)
    col_list = ", ".join([r['column_name'] for r in cols])

    # Use Smart Capture extract (routes through n8n which has Anthropic creds)
    # Pass the page content as text with a hint about what columns to fill
    domain_hints = {
        "tools": "tool", "saw_blades": "saw_blade", "router_bits": "router_bit",
        "wood": "wood", "albums": "album", "manuals": "manual",
    }
    extract_text = f"Extract product info from this URL: {url}\n\nAvailable columns: {col_list}\n\nPage content:\n{page_text[:6000]}"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{N8N_BASE}/webhook/smart-capture/extract",
                json={
                    "text": extract_text,
                    "domain_hint": domain_hints.get(table, ""),
                }
            )
            data = resp.json()

            # Parse intents from response
            intents = []
            if isinstance(data, dict) and data.get("ok") and data.get("intents"):
                intents = data["intents"]
            elif isinstance(data, dict) and data.get("content"):
                import re
                text = data["content"][0]["text"]
                text = re.sub(r'```json\n?', '', text)
                text = text.replace('```', '').strip()
                intents = json.loads(text).get("intents", [])

            if intents:
                payload = intents[0].get("payload", {})
                extras = payload.pop("_extra_fields", {})
                fields = {**payload}
                if extras:
                    extra_str = "; ".join(f"{k}: {v}" for k, v in extras.items())
                    fields["notes"] = ((fields.get("notes") or "") + "\n--- from URL ---\n" + extra_str).strip()
                # Add the URL itself
                if "url" in [r['column_name'] for r in cols]:
                    fields["url"] = url
                return {"ok": True, "fields": fields, "url": url}
            else:
                return {"ok": False, "error": "AI could not extract fields from page content"}
    except Exception as e:
        return {"ok": False, "error": f"Extraction failed: {str(e)}"}


@app.post("/api/inbox-process")
async def inbox_process(request: Request):
    """Process inbox files: create a new row in a table and link selected images to it.
    Body: {
        schema: "inventory",
        table: "tools",
        files: ["inbox/photo1.jpg", "inbox/photo2.jpg"],
        row_data: {name: "My Tool", brand: "DeWalt"},  // optional — fields for the new row
        existing_row_id: null  // if set, link to existing row instead of creating new
    }
    """
    body = await request.json()
    schema = body.get("schema", "").strip()
    table = body.get("table", "").strip()
    file_paths = body.get("files", [])
    row_data = body.get("row_data", {})
    existing_row_id = body.get("existing_row_id")

    if not schema or not table:
        raise HTTPException(status_code=400, detail="schema and table required")
    if not file_paths:
        raise HTTPException(status_code=400, detail="files array required (at least one)")

    link_info = get_link_table_info(schema, table)
    if not link_info:
        raise HTTPException(status_code=400, detail=f"{schema}.{table} does not support images")

    link_schema, link_table, fk_col = link_info

    # Determine the row to link to
    row_id = existing_row_id
    if not row_id:
        # Create a new row with provided data (or minimal defaults)
        if not row_data:
            # At minimum, need a name or something — use first filename
            first_file = file_paths[0].split('/')[-1].rsplit('.', 1)[0]
            row_data = {"name": first_file}

        # Get column types
        col_types = {}
        col_rows = await pool.fetch("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
        """, schema, table)
        for r in col_rows:
            col_types[r["column_name"]] = r["data_type"]

        # Filter to valid columns only
        valid_cols = set(col_types.keys()) - {'id', 'created_at', 'updated_at', 'archived_at'}
        insert_data = {k: v for k, v in row_data.items() if k in valid_cols and v}

        if not insert_data:
            # Fallback: just insert with defaults
            result = await pool.fetchrow(
                f'INSERT INTO "{schema}"."{table}" DEFAULT VALUES RETURNING id'
            )
        else:
            cols = []
            placeholders = []
            params = []
            idx = 1
            for col, val in insert_data.items():
                cols.append(f'"{col}"')
                placeholders.append(f"${idx}")
                params.append(cast_value(val, col_types.get(col, 'text')))
                idx += 1
            query = f'INSERT INTO "{schema}"."{table}" ({", ".join(cols)}) VALUES ({", ".join(placeholders)}) RETURNING id'
            result = await pool.fetchrow(query, *params)

        row_id = result["id"]

    # Now link each file
    linked = []
    for i, file_path in enumerate(file_paths):
        full_path = FILES_ROOT / file_path
        if not full_path.exists():
            linked.append({"file": file_path, "error": "not found"})
            continue

        content = full_path.read_bytes()
        sha = hashlib.sha256(content).hexdigest()
        mime = mimetypes.guess_type(full_path.name)[0] or "application/octet-stream"
        filename = full_path.name

        # Check for existing asset with same sha256
        existing_asset = await pool.fetchval(
            "SELECT id FROM files.assets WHERE sha256 = $1", sha
        )

        if existing_asset:
            asset_id = existing_asset
        else:
            # Insert asset row
            row = await pool.fetchrow("""
                INSERT INTO files.assets (path, original_name, mime, size_bytes, sha256, domain, uploaded_by)
                VALUES ($1, $2, $3, $4, $5, $6, 'db-admin-inbox')
                RETURNING id
            """, str(full_path), filename, mime, len(content), sha, schema)
            asset_id = row["id"]

        # Link to the row
        is_primary = (i == 0)  # First image is primary
        try:
            await pool.execute(f"""
                INSERT INTO "{link_schema}"."{link_table}" ("{fk_col}", asset_id, is_primary)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
            """, row_id, asset_id, is_primary)
            linked.append({"file": file_path, "asset_id": str(asset_id), "linked": True})
        except Exception as e:
            linked.append({"file": file_path, "error": str(e)})

    return {
        "ok": True,
        "row_id": row_id,
        "schema": schema,
        "table": table,
        "linked": linked,
    }


@app.post("/api/inbox-knowledge")
async def inbox_knowledge(request: Request):
    """Save inbox files as a knowledge note with photos.
    Body: {
        topic: "household/pets",
        title: "Opal",
        content: "Opal is my cat. She is...",
        files: ["inbox/opal.jpg", ...]
    }
    Creates a markdown file at /knowledge/<topic>/<slug>.md with embedded photo references.
    Files are moved from inbox to /files/knowledge/<slug>/ and registered in files.assets.
    """
    body = await request.json()
    topic = (body.get("topic") or "general").strip().strip('/')
    title = (body.get("title") or "").strip()
    content = (body.get("content") or "").strip()
    file_paths = body.get("files", [])

    if not title:
        raise HTTPException(status_code=400, detail="title required")
    if not content and not file_paths:
        raise HTTPException(status_code=400, detail="content or files required")

    # Normalize topic to a path-safe slug
    topic_safe = "/".join(p.lower().replace(" ", "-").replace("/", "-") for p in topic.split("/") if p)
    if not topic_safe:
        topic_safe = "general"

    # Create slug from title
    import re
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60] or "untitled"

    # Move files to knowledge storage
    knowledge_files_dir = FILES_ROOT / "knowledge" / slug
    knowledge_files_dir.mkdir(parents=True, exist_ok=True)
    moved_files = []
    asset_ids = []
    for file_path in file_paths:
        src = FILES_ROOT / file_path
        if not src.exists():
            continue
        dest = knowledge_files_dir / src.name
        # Avoid overwrites
        if dest.exists() and dest != src:
            counter = 1
            stem, suffix = dest.stem, dest.suffix
            while dest.exists():
                dest = knowledge_files_dir / f"{stem}_{counter}{suffix}"
                counter += 1
        if src != dest:
            src.rename(dest)
        moved_files.append(dest)

        # Register asset in DB for searchability
        try:
            content_bytes = dest.read_bytes()
            sha = hashlib.sha256(content_bytes).hexdigest()
            mime = mimetypes.guess_type(dest.name)[0] or "application/octet-stream"
            existing = await pool.fetchval("SELECT id FROM files.assets WHERE sha256 = $1", sha)
            if existing:
                asset_ids.append(str(existing))
            else:
                row = await pool.fetchrow("""
                    INSERT INTO files.assets (path, original_name, mime, size_bytes, sha256, domain, uploaded_by)
                    VALUES ($1, $2, $3, $4, $5, 'knowledge', 'db-admin-inbox')
                    RETURNING id
                """, str(dest), src.name, mime, len(content_bytes), sha)
                asset_ids.append(str(row["id"]))
        except Exception:
            pass

    # Build markdown content with photo embeds
    today = datetime.now().date().isoformat()
    md_lines = [
        f"# {title}",
        "",
        f"_Saved: {today} | Topic: {topic_safe}_",
        "",
    ]
    if content:
        md_lines.append(content)
        md_lines.append("")
    if moved_files:
        md_lines.append("## Photos")
        md_lines.append("")
        for f in moved_files:
            relative = f.relative_to(FILES_ROOT)
            md_lines.append(f"![{f.stem}](/files/{relative})")
            md_lines.append("")

    markdown = "\n".join(md_lines)

    # Write to knowledge directory via filewriter
    knowledge_path = f"/knowledge/{topic_safe}/{slug}.md"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post("http://100.106.180.101:5001/append", json={
                "path": knowledge_path,
                "content": markdown + "\n",
            })
            if resp.status_code != 200:
                # Fallback: write directly
                full_path = Path("/knowledge") / topic_safe / f"{slug}.md"
                full_path.parent.mkdir(parents=True, exist_ok=True)
                full_path.write_text(markdown + "\n")
    except Exception as e:
        # If filewriter is unreachable, just return success with the data ready
        pass

    return {
        "ok": True,
        "topic": topic_safe,
        "title": title,
        "slug": slug,
        "knowledge_path": knowledge_path,
        "files_moved": len(moved_files),
        "asset_ids": asset_ids,
    }


@app.get("/inbox", response_class=HTMLResponse)
async def inbox_page():
    """Inbox processing page — group and assign photos to records without AI."""
    inbox_html = (Path(__file__).parent / "static" / "inbox.html").read_text()
    return HTMLResponse(content=inbox_html)


@app.get("/settings", response_class=HTMLResponse)
async def settings_page():
    """Field Properties Settings page."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Field Settings — DB Admin</title>
    <link rel="stylesheet" href="/static/style.css">
    <style>
        .settings-app { max-width: 1100px; margin: 0 auto; padding: 1.5rem; }
        .settings-header { display: flex; align-items: center; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
        .settings-header h1 { font-size: 1.3rem; color: var(--accent); }
        .settings-header .back { color: var(--text-muted); text-decoration: none; font-size: 0.85rem; }
        .settings-header .back:hover { color: var(--accent); }
        .search-filter { margin-left: auto; }
        .search-filter input { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 0.4rem 0.75rem; color: var(--text); font-size: 0.85rem; width: 220px; }
        .search-filter input:focus { outline: none; border-color: var(--accent); }
        .hint-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; }
        .hint-table th { text-align: left; padding: 0.6rem 0.75rem; color: var(--text-muted); border-bottom: 1px solid var(--border); font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.03em; position: sticky; top: 0; background: var(--bg); z-index: 1; }
        .hint-table td { padding: 0.5rem 0.75rem; border-bottom: 1px solid var(--border); vertical-align: middle; }
        .hint-table tr:hover td { background: var(--surface-hover); }
        .hint-table .col-name { font-family: var(--mono); font-weight: 500; color: var(--text); }
        .hint-table .col-tables { font-size: 0.7rem; color: var(--text-muted); max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .hint-table .col-tables:hover { white-space: normal; overflow: visible; }
        .hint-table select, .hint-table input { background: var(--input-bg); border: 1px solid var(--border); border-radius: 4px; padding: 0.3rem 0.5rem; color: var(--text); font-size: 0.8rem; }
        .hint-table select { min-width: 90px; }
        .hint-table input { width: 70px; }
        .hint-table input.wide { width: 140px; }
        .hint-table .options-input { width: 180px; }
        .btn-save-hint { background: var(--success); color: var(--bg); border: none; padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; font-size: 0.75rem; }
        .btn-save-hint:hover { opacity: 0.9; }
        .btn-reset-hint { background: none; border: 1px solid var(--border); color: var(--text-muted); padding: 0.25rem 0.5rem; border-radius: 4px; cursor: pointer; font-size: 0.75rem; }
        .btn-reset-hint:hover { border-color: var(--danger); color: var(--danger); }
        .saved-badge { display: inline-block; background: var(--accent); color: var(--bg); font-size: 0.65rem; padding: 0.1rem 0.4rem; border-radius: 3px; margin-left: 0.5rem; }
        .type-fields { display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap; }
        .stats { color: var(--text-muted); font-size: 0.8rem; margin-bottom: 1rem; }
        .filter-btns { display: flex; gap: 0.4rem; margin-bottom: 1rem; flex-wrap: wrap; }
        .filter-btns button { padding: 0.25rem 0.6rem; border-radius: 4px; border: 1px solid var(--border); background: var(--surface); color: var(--text-muted); cursor: pointer; font-size: 0.75rem; }
        .filter-btns button.active { background: var(--accent); color: var(--bg); border-color: var(--accent); }
        .filter-btns button:hover:not(.active) { border-color: var(--accent); color: var(--text); }
    </style>
</head>
<body>
<div class="settings-app">
    <div class="settings-header">
        <a href="/" class="back">← DB Admin</a>
        <h1>⚙ Field Properties</h1>
        <div class="search-filter">
            <input type="text" id="search" placeholder="Filter columns..." />
        </div>
    </div>
    <div class="filter-btns" id="filter-btns">
        <button class="active" data-filter="all">All</button>
        <button data-filter="configured">Configured</button>
        <button data-filter="unconfigured">Unconfigured</button>
    </div>
    <div class="stats" id="stats"></div>
    <div style="overflow-x:auto;">
        <table class="hint-table">
            <thead>
                <tr>
                    <th>Column Name</th>
                    <th>Used In</th>
                    <th>Type</th>
                    <th>Config</th>
                    <th></th>
                </tr>
            </thead>
            <tbody id="hints-body"></tbody>
        </table>
    </div>
</div>
<script>
let allColumns = {};
let savedHints = {};
let currentFilter = 'all';

async function load() {
    const [cols, hints] = await Promise.all([
        fetch('/api/all-columns').then(r => r.json()),
        fetch('/api/field-hints').then(r => r.json()),
    ]);
    allColumns = cols;
    savedHints = hints;
    render();
}

function render() {
    const search = document.getElementById('search').value.toLowerCase();
    const tbody = document.getElementById('hints-body');
    tbody.innerHTML = '';

    const entries = Object.entries(allColumns)
        .filter(([name]) => name.toLowerCase().includes(search))
        .filter(([name]) => {
            if (currentFilter === 'configured') return !!savedHints[name];
            if (currentFilter === 'unconfigured') return !savedHints[name];
            return true;
        })
        .sort((a, b) => {
            // Configured first, then alphabetical
            const aConf = savedHints[a[0]] ? 0 : 1;
            const bConf = savedHints[b[0]] ? 0 : 1;
            if (aConf !== bConf) return aConf - bConf;
            return a[0].localeCompare(b[0]);
        });

    document.getElementById('stats').textContent =
        `${Object.keys(allColumns).length} columns total · ${Object.keys(savedHints).length} configured · showing ${entries.length}`;

    for (const [colName, info] of entries) {
        const hint = savedHints[colName] || {};
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td class="col-name">${colName}${savedHints[colName] ? '<span class="saved-badge">saved</span>' : ''}</td>
            <td class="col-tables" title="${info.tables.join(', ')}">${info.tables.slice(0, 3).join(', ')}${info.tables.length > 3 ? ' +' + (info.tables.length - 3) : ''}</td>
            <td>
                <select data-col="${colName}" class="type-select">
                    ${['text','number','fraction','select','url','date','boolean'].map(t =>
                        `<option value="${t}" ${(hint.type || detectType(colName, info.data_type)) === t ? 'selected' : ''}>${t}</option>`
                    ).join('')}
                </select>
            </td>
            <td class="type-fields" id="config-${colName}"></td>
            <td>
                <button class="btn-save-hint" onclick="saveHint('${colName}')">Save</button>
                ${savedHints[colName] ? `<button class="btn-reset-hint" onclick="resetHint('${colName}')">Reset</button>` : ''}
            </td>
        `;
        tbody.appendChild(tr);

        // Render type-specific config fields
        renderConfig(colName, hint);

        // Type change handler
        tr.querySelector('.type-select').addEventListener('change', (e) => {
            renderConfig(colName, { ...hint, type: e.target.value });
        });
    }
}

function detectType(colName, dataType) {
    if (colName.endsWith('_at') || dataType === 'date') return 'date';
    if (colName.startsWith('has_') || colName.startsWith('is_') || dataType === 'boolean') return 'boolean';
    if (colName === 'url' || colName.endsWith('_url')) return 'url';
    if (dataType && ['numeric','integer','bigint','smallint','real','double precision'].includes(dataType)) return 'number';
    return 'text';
}

function renderConfig(colName, hint) {
    const td = document.getElementById(`config-${colName}`);
    if (!td) return;
    const type = hint.type || 'text';

    let html = '';
    if (type === 'number' || type === 'fraction') {
        html = `
            <input type="text" class="wide" data-field="prefix" placeholder="prefix ($)" value="${hint.prefix || ''}" />
            <input type="text" data-field="suffix" placeholder="suffix" value="${hint.suffix || ''}" />
            <input type="number" data-field="min" placeholder="min" value="${hint.min != null ? hint.min : ''}" />
            <input type="number" data-field="max" placeholder="max" value="${hint.max != null ? hint.max : ''}" />
            <input type="number" data-field="step" placeholder="step" value="${hint.step != null ? hint.step : ''}" />
            <input type="text" class="wide" data-field="placeholder" placeholder="placeholder" value="${hint.placeholder || ''}" />
        `;
    } else if (type === 'select') {
        const opts = (hint.options || []).join(', ');
        html = `<input type="text" class="options-input" data-field="options" placeholder="option1, option2, ..." value="${opts}" />`;
    } else if (type === 'url' || type === 'date' || type === 'boolean' || type === 'text') {
        html = `<input type="text" data-field="placeholder" placeholder="placeholder text" value="${hint.placeholder || ''}" />`;
    }
    td.innerHTML = html;
}

async function saveHint(colName) {
    const row = document.querySelector(`[data-col="${colName}"]`).closest('tr');
    const type = row.querySelector('.type-select').value;
    const configTd = document.getElementById(`config-${colName}`);

    const body = { type };

    const prefix = configTd.querySelector('[data-field="prefix"]');
    const suffix = configTd.querySelector('[data-field="suffix"]');
    const min = configTd.querySelector('[data-field="min"]');
    const max = configTd.querySelector('[data-field="max"]');
    const step = configTd.querySelector('[data-field="step"]');
    const placeholder = configTd.querySelector('[data-field="placeholder"]');
    const options = configTd.querySelector('[data-field="options"]');

    if (prefix && prefix.value) body.prefix = prefix.value;
    if (suffix && suffix.value) body.suffix = suffix.value;
    if (min && min.value !== '') body.min = parseFloat(min.value);
    if (max && max.value !== '') body.max = parseFloat(max.value);
    if (step && step.value !== '') body.step = parseFloat(step.value);
    if (placeholder && placeholder.value) body.placeholder = placeholder.value;
    if (options && options.value) body.options = options.value.split(',').map(s => s.trim()).filter(Boolean);

    const resp = await fetch(`/api/field-hints/${colName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (data.ok) {
        savedHints[colName] = body;
        render();
    }
}

async function resetHint(colName) {
    if (!confirm(`Reset "${colName}" to auto-detection?`)) return;
    const resp = await fetch(`/api/field-hints/${colName}`, { method: 'DELETE' });
    const data = await resp.json();
    if (data.ok) {
        delete savedHints[colName];
        render();
    }
}

// Filter buttons
document.getElementById('filter-btns').addEventListener('click', (e) => {
    if (e.target.tagName !== 'BUTTON') return;
    currentFilter = e.target.dataset.filter;
    document.querySelectorAll('#filter-btns button').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    render();
});

document.getElementById('search').addEventListener('input', render);
load();
</script>
</body>
</html>"""
    return HTMLResponse(content=html)


# --- Inbox Upload (phone-friendly) -------------------------------------------


@app.post("/api/inbox-upload")
async def inbox_upload(files: list[UploadFile] = File(...)):
    """Upload one or more files directly to /files/inbox/. No processing — just drops them."""
    inbox = FILES_ROOT / "inbox"
    inbox.mkdir(parents=True, exist_ok=True)

    results = []
    for file in files:
        filename = file.filename or "upload.jpg"
        # Sanitize filename
        filename = filename.replace("/", "_").replace("\\", "_").replace("..", "_")
        dest = inbox / filename

        # If file already exists, add a suffix
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            i = 1
            while dest.exists():
                dest = inbox / f"{stem}_{i}{suffix}"
                i += 1

        content = await file.read()
        dest.write_bytes(content)
        results.append({
            "filename": dest.name,
            "size_bytes": len(content),
            "path": f"inbox/{dest.name}",
        })

    return {"ok": True, "uploaded": len(results), "files": results}


# --- Batch Inbox Processing ---------------------------------------------------


@app.get("/api/unlinked-assets")
async def get_unlinked_assets(domain: str = "tool", limit: int = 100, include_unprocessed: bool = True):
    """List assets that aren't linked to any inventory row.
    Includes assets pending re-processing (ai_extracted IS NULL) by default.
    """
    extracted_filter = "" if include_unprocessed else "AND a.ai_extracted IS NOT NULL"
    rows = await pool.fetch(f"""
        SELECT a.id, a.original_name, a.path, a.mime, a.ai_summary, a.ai_extracted, a.uploaded_at
        FROM files.assets a
        WHERE a.domain = $1
          {extracted_filter}
          AND NOT EXISTS (SELECT 1 FROM inventory.tool_files       WHERE asset_id = a.id)
          AND NOT EXISTS (SELECT 1 FROM inventory.router_bit_files WHERE asset_id = a.id)
          AND NOT EXISTS (SELECT 1 FROM inventory.saw_blade_files  WHERE asset_id = a.id)
          AND NOT EXISTS (SELECT 1 FROM inventory.album_files      WHERE asset_id = a.id)
          AND NOT EXISTS (SELECT 1 FROM inventory.manual_files     WHERE asset_id = a.id)
          AND NOT EXISTS (SELECT 1 FROM inventory.wood_files       WHERE asset_id = a.id)
        ORDER BY a.uploaded_at DESC
        LIMIT $2
    """, domain, limit)

    result = []
    for r in rows:
        path = r["path"] or ""
        path = path.replace("/home/michael/files/", "").replace("/files/", "")
        result.append({
            "asset_id": str(r["id"]),
            "original_name": r["original_name"],
            "thumb_url": f"/files/{path}",
            "is_image": (r["mime"] or "").startswith("image/"),
            "ai_summary": r["ai_summary"],
            "ai_extracted": r["ai_extracted"],
            "needs_processing": r["ai_extracted"] is None,
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
        })

    return {"assets": result, "count": len(result)}


@app.post("/api/lookup-url")
async def lookup_url(request: Request):
    """Fetch a product URL and extract structured fields using Haiku.
    Body: {url: "https://...", target_table: "inventory.tools"}
    Returns: {ok, extracted: {brand, model, name, type, notes, ...}}
    """
    body = await request.json()
    url = (body.get("url") or "").strip()
    target_table = body.get("target_table", "inventory.tools")

    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Valid URL required")

    # Get target table columns to tell Haiku what to extract
    columns = []
    if "." in target_table:
        schema, table = target_table.split(".", 1)
        col_rows = await pool.fetch("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
              AND column_name NOT IN ('id', 'created_at', 'updated_at', 'archived_at')
            ORDER BY ordinal_position
        """, schema, table)
        columns = [r["column_name"] for r in col_rows]

    # Fetch the URL content
    page_text = ""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; 595BowersHub/1.0)"
            })
            if resp.status_code == 200:
                # Strip HTML tags, keep text
                import re
                html = resp.text[:50000]  # cap at 50KB
                page_text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
                page_text = re.sub(r'<style[^>]*>.*?</style>', '', page_text, flags=re.DOTALL | re.IGNORECASE)
                page_text = re.sub(r'<[^>]+>', ' ', page_text)
                page_text = re.sub(r'\s+', ' ', page_text).strip()
                page_text = page_text[:8000]  # keep first 8K chars for Haiku
            else:
                return {"ok": False, "error": f"URL returned HTTP {resp.status_code}"}
    except Exception as e:
        return {"ok": False, "error": f"Failed to fetch URL: {str(e)}"}

    if not page_text or len(page_text) < 50:
        return {"ok": False, "error": "Could not extract meaningful text from URL"}

    # Build Haiku prompt
    col_list = ", ".join(columns) if columns else "brand, model, name, type, notes"
    prompt = f"""You are extracting product information from a web page. 
Return ONLY a JSON object with these fields: {col_list}
Use null for any field you cannot determine from the page content.
For numeric fields (like dimensions), return just the number.
For price fields, return just the number (no $ sign).

Page content:
{page_text}

Return the JSON object and nothing else."""

    # Call Haiku
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            haiku_resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                    "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )

            if haiku_resp.status_code != 200:
                # Try via n8n webhook as fallback (uses credential-based auth)
                n8n_resp = await client.post(
                    f"{N8N_BASE}/webhook/log-api-usage",
                    json={"workflow_name": "URL Lookup (failed)", "node_name": "direct", "model": "claude-haiku-4-5-20251001", "input_tokens": 0, "output_tokens": 0},
                )
                return {"ok": False, "error": f"Anthropic API returned {haiku_resp.status_code}"}

            data = haiku_resp.json()
            text = data.get("content", [{}])[0].get("text", "")
            text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            # Log usage
            usage = data.get("usage", {})
            try:
                await client.post(
                    f"{N8N_BASE}/webhook/log-api-usage",
                    json={
                        "workflow_name": "URL Lookup",
                        "node_name": "lookup-url",
                        "model": "claude-haiku-4-5-20251001",
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                    },
                )
            except Exception:
                pass

            extracted = json.loads(text)
            return {"ok": True, "extracted": extracted, "url": url}

    except json.JSONDecodeError:
        return {"ok": False, "error": "Haiku returned invalid JSON", "raw": text[:500]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/reprocess-asset")
async def reprocess_asset(request: Request):
    """Re-run vision on an existing asset to get fresh AI extraction.
    Does NOT delete the asset — updates it in place.
    Body: {asset_id: "uuid", domain_hint: "tool"}
    """
    body = await request.json()
    asset_id = body.get("asset_id")
    domain_hint = body.get("domain_hint", "tool")

    if not asset_id:
        raise HTTPException(status_code=400, detail="asset_id required")

    # Get the asset's current path
    row = await pool.fetchrow(
        "SELECT id, path, original_name, mime FROM files.assets WHERE id = $1",
        UUID(asset_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")

    file_path = row["path"]
    rel_path = file_path.replace("/files/", "").replace("/home/michael/files/", "")

    # Read the file as base64 via filewriter (with auto-resize for large images)
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            b64_resp = await client.post("http://100.106.180.101:5001/read-base64", json={
                "path": file_path,
                "max_bytes": 4500000,  # 4.5MB raw = under 5MB after base64
            })
            if b64_resp.status_code != 200 or not b64_resp.json().get("ok"):
                return {"ok": False, "error": f"Could not read file: {file_path}"}
            b64_data = b64_resp.json()["base64"]
    except Exception as e:
        return {"ok": False, "error": f"File read failed: {str(e)}"}

    # Build vision prompt
    PROMPTS = {
        "tool": "You are inventorying a tool. Return ONLY JSON: {brand, model, type, name, serial, condition, notes}. Use null when unknown. type is e.g. 'saw', 'drill', 'chisel'.",
        "saw_blade": "Inventorying a saw blade. Return ONLY JSON: {brand, diameter_in, teeth, kerf_in, type, notes}. type is rip|crosscut|combo|dado|other. Use null if unknown.",
        "wood": "Inventorying lumber. Return ONLY JSON: {species, dimensions, quantity, unit, notes}. unit is bf|lf|board|other.",
        "album": "Inventorying a vinyl record. Return ONLY JSON: {title, artist, label, catalog_number, year, condition, notes}.",
        "manual": "Identifying a product manual or spec sheet. Return ONLY JSON: {title, brand, model, doc_type, notes}.",
    }
    prompt = PROMPTS.get(domain_hint, PROMPTS["tool"])
    mime = row["mime"] or "image/jpeg"

    # Call Anthropic directly
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"ok": False, "error": "ANTHROPIC_API_KEY not configured"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "Content-Type": "application/json",
                    "anthropic-version": "2023-06-01",
                    "x-api-key": api_key,
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": mime, "data": b64_data}},
                            {"type": "text", "text": prompt + "\n\nReturn the JSON object and nothing else."},
                        ],
                    }],
                },
            )

            if resp.status_code != 200:
                return {"ok": False, "error": f"Anthropic returned {resp.status_code}: {resp.text[:200]}"}

            data = resp.json()
            text = (data.get("content", [{}])[0].get("text", "")).strip()
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            # Parse and build summary
            extracted = json.loads(text)
            parts = []
            if extracted.get("brand"): parts.append(extracted["brand"])
            if extracted.get("name"): parts.append(extracted["name"])
            elif extracted.get("model"): parts.append(extracted["model"])
            elif extracted.get("title"): parts.append(extracted["title"])
            elif extracted.get("type"): parts.append(extracted["type"])
            summary = " ".join(parts) if parts else "unknown item"

            # Update the asset row in place
            await pool.execute("""
                UPDATE files.assets SET
                    ai_summary = $1,
                    ai_extracted = $2::jsonb,
                    ai_model = 'claude-haiku-4-5-20251001',
                    domain = $3,
                    processed_at = now()
                WHERE id = $4
            """, summary, json.dumps(extracted), domain_hint, UUID(asset_id))

            # Log usage
            usage = data.get("usage", {})
            try:
                await client.post(
                    f"{N8N_BASE}/webhook/log-api-usage",
                    json={
                        "workflow_name": "Reprocess Asset",
                        "node_name": "reprocess-vision",
                        "model": "claude-haiku-4-5-20251001",
                        "input_tokens": usage.get("input_tokens", 0),
                        "output_tokens": usage.get("output_tokens", 0),
                        "cache_read_tokens": 0,
                        "cache_write_tokens": 0,
                    },
                )
            except Exception:
                pass

            return {
                "ok": True,
                "asset_id": asset_id,
                "ai_summary": summary,
                "ai_extracted": extracted,
                "domain": domain_hint,
            }

    except json.JSONDecodeError:
        return {"ok": False, "error": "Vision returned invalid JSON"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/api/move-to-inbox")
async def move_asset_to_inbox(request: Request):
    """Move an asset's file back to /files/inbox/ and reset it for reprocessing.
    Body: {asset_id: "uuid"}
    """
    body = await request.json()
    asset_id = body.get("asset_id")

    if not asset_id:
        raise HTTPException(status_code=400, detail="asset_id required")

    row = await pool.fetchrow(
        "SELECT id, path, original_name FROM files.assets WHERE id = $1",
        UUID(asset_id)
    )
    if not row:
        raise HTTPException(status_code=404, detail="Asset not found")

    current_path = Path(row["path"].replace("/home/michael/files", str(FILES_ROOT)))
    original_name = row["original_name"] or current_path.name
    inbox_dest = FILES_ROOT / "inbox" / original_name

    # Avoid overwriting
    if inbox_dest.exists():
        stem = inbox_dest.stem
        suffix = inbox_dest.suffix
        i = 1
        while inbox_dest.exists():
            inbox_dest = FILES_ROOT / "inbox" / f"{stem}_{i}{suffix}"
            i += 1

    # Move the file
    if current_path.exists():
        inbox_dest.parent.mkdir(parents=True, exist_ok=True)
        current_path.rename(inbox_dest)

    # Delete the asset row entirely (clean slate)
    await pool.execute("DELETE FROM files.assets WHERE id = $1", UUID(asset_id))

    return {
        "ok": True,
        "moved_to": f"inbox/{inbox_dest.name}",
        "deleted_asset": asset_id,
    }


@app.post("/api/inbox-delete")
async def delete_inbox_files(request: Request):
    """Delete files from /files/inbox/. Body: {files: ["inbox/file1.jpg", ...]}"""
    body = await request.json()
    file_paths = body.get("files", [])

    if not file_paths:
        raise HTTPException(status_code=400, detail="No files specified")

    deleted = []
    errors = []
    for file_path in file_paths:
        # Security: only allow inbox/ paths
        if not file_path.startswith("inbox/"):
            errors.append({"file": file_path, "error": "Only inbox files can be deleted"})
            continue

        full_path = FILES_ROOT / file_path
        # Prevent path traversal
        try:
            full_path.resolve().relative_to((FILES_ROOT / "inbox").resolve())
        except ValueError:
            errors.append({"file": file_path, "error": "Invalid path"})
            continue

        if full_path.exists() and full_path.is_file():
            full_path.unlink()
            deleted.append(file_path)
        else:
            errors.append({"file": file_path, "error": "File not found"})

    return {"ok": True, "deleted": len(deleted), "errors": errors}


@app.get("/api/inbox-files")
async def list_inbox_files():
    """List all files currently in /files/inbox/ with thumbnails."""
    inbox = FILES_ROOT / "inbox"
    if not inbox.exists():
        return {"files": []}

    files = []
    for f in sorted(inbox.iterdir()):
        if f.is_file() and not f.name.startswith('.'):
            mime = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            files.append({
                "name": f.name,
                "path": f"inbox/{f.name}",
                "size_bytes": f.stat().st_size,
                "mime": mime,
                "is_image": mime.startswith("image/"),
                "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
            })

    return {"files": files, "count": len(files)}


@app.post("/api/inbox-process")
async def process_inbox_files(request: Request):
    """
    Process one or more inbox files through Haiku vision.
    Returns extracted data for staging (does NOT commit to DB).

    Body: {
        files: ["inbox/photo1.jpg", "inbox/photo2.jpg"],
        target_table: "inventory.tools",
        domain_hint: "tool"
    }

    Returns: {
        ok: true,
        results: [
            {
                file: "inbox/photo1.jpg",
                asset_id: "uuid",
                ai_summary: "...",
                ai_extracted: {...},
                suggested_values: {...},  // mapped to target table columns
                status: "ok" | "error",
                error: null | "..."
            }
        ]
    }
    """
    body = await request.json()
    file_paths = body.get("files", [])
    target_table = body.get("target_table", "")
    domain_hint = body.get("domain_hint", "tool")

    if not file_paths:
        raise HTTPException(status_code=400, detail="No files specified")

    # Get target table columns for mapping
    target_columns = []
    if target_table and "." in target_table:
        schema, table = target_table.split(".", 1)
        col_rows = await pool.fetch("""
            SELECT column_name, data_type FROM information_schema.columns
            WHERE table_schema = $1 AND table_name = $2
            ORDER BY ordinal_position
        """, schema, table)
        target_columns = [{"name": r["column_name"], "type": r["data_type"]} for r in col_rows]

    results = []
    for file_path in file_paths:
        result = {
            "file": file_path,
            "asset_id": None,
            "ai_summary": None,
            "ai_extracted": None,
            "suggested_values": {},
            "status": "error",
            "error": None,
        }

        try:
            # Call Process Asset webhook
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(f"{N8N_BASE}/webhook/process-asset", json={
                    "path": file_path,
                    "domain_hint": domain_hint,
                    "uploaded_by": "db-admin-batch",
                    "original_name": Path(file_path).name,
                })

                if resp.status_code == 200:
                    data = resp.json()
                    result["asset_id"] = data.get("asset_id")
                    result["ai_summary"] = data.get("ai_summary")
                    result["ai_extracted"] = data.get("ai_extracted")
                    result["status"] = "ok"

                    # Map ai_extracted fields to target table columns
                    extracted = data.get("ai_extracted") or {}
                    if isinstance(extracted, str):
                        try:
                            extracted = json.loads(extracted)
                        except (json.JSONDecodeError, TypeError):
                            extracted = {}

                    suggested = {}
                    col_names = {c["name"] for c in target_columns}

                    # Direct field mapping (extracted field name matches column name)
                    for key, val in extracted.items():
                        if val is None:
                            continue
                        # Try exact match
                        if key in col_names:
                            suggested[key] = val
                        # Try common mappings
                        elif key == "type" and "type" in col_names:
                            suggested["type"] = val
                        elif key == "serial" and "serial_number" in col_names:
                            suggested["serial_number"] = val
                        elif key == "serial" and "model_number" in col_names:
                            suggested["model_number"] = val

                    # Always include name/brand if available
                    if "name" in extracted and "name" in col_names:
                        suggested["name"] = extracted["name"]
                    if "brand" in extracted and "brand" in col_names:
                        suggested["brand"] = extracted["brand"]

                    result["suggested_values"] = suggested
                else:
                    result["error"] = f"Process Asset returned {resp.status_code}: {resp.text[:200]}"

        except Exception as e:
            result["error"] = str(e)

        results.append(result)

    return {"ok": True, "results": results, "target_columns": target_columns}


@app.post("/api/inbox-commit")
async def commit_staged_rows(request: Request):
    """
    Commit staged rows to the database.
    Body: {
        target_table: "inventory.tools",
        rows: [
            { values: {name: "...", brand: "..."}, asset_id: "uuid", asset_ids: ["uuid1", "uuid2"] },
            ...
        ]
    }
    asset_id = primary photo (made primary in link table)
    asset_ids = additional photos to link (optional)
    Returns: { ok, committed: N, errors: [...] }
    """
    body = await request.json()
    target_table = body.get("target_table", "")
    rows = body.get("rows", [])

    if not target_table or "." not in target_table:
        raise HTTPException(status_code=400, detail="target_table required (schema.table)")
    if not rows:
        raise HTTPException(status_code=400, detail="No rows to commit")

    schema, table = target_table.split(".", 1)

    # Verify table exists
    exists = await pool.fetchval("""
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    if not exists:
        raise HTTPException(status_code=404, detail=f"Table {target_table} not found")

    # Get column types
    col_types = {}
    col_rows = await pool.fetch("""
        SELECT column_name, data_type FROM information_schema.columns
        WHERE table_schema = $1 AND table_name = $2
    """, schema, table)
    for r in col_rows:
        col_types[r["column_name"]] = r["data_type"]

    # Get link table info for asset linking
    link_info = get_link_table_info(schema, table)

    committed = 0
    errors = []

    for i, row in enumerate(rows):
        values = row.get("values", {})
        asset_id = row.get("asset_id")
        extra_assets = row.get("asset_ids", [])  # additional photos to link

        if not values:
            errors.append({"index": i, "error": "No values provided"})
            continue

        # Filter to valid columns only, skip auto-generated ones
        skip_cols = {'id', 'created_at', 'updated_at', 'archived_at'}
        filtered = {k: v for k, v in values.items()
                    if k in col_types and k not in skip_cols and v is not None and v != ''}

        if not filtered:
            errors.append({"index": i, "error": "No valid columns after filtering"})
            continue

        # Build INSERT
        cols = []
        placeholders = []
        params = []
        idx = 1
        for col, val in filtered.items():
            cols.append(f'"{col}"')
            placeholders.append(f"${idx}")
            params.append(cast_value(val, col_types.get(col, 'text')))
            idx += 1

        query = f'INSERT INTO "{schema}"."{table}" ({", ".join(cols)}) VALUES ({", ".join(placeholders)}) RETURNING id'

        try:
            new_id = await pool.fetchval(query, *params)

            # Link primary asset and any extras
            if link_info:
                link_schema, link_table, fk_col = link_info

                # Combine primary + extras (primary first, marked as is_primary)
                all_assets = []
                if asset_id:
                    all_assets.append((asset_id, True))
                for extra in extra_assets:
                    if extra and extra != asset_id:
                        all_assets.append((extra, False))

                for aid, is_primary in all_assets:
                    try:
                        await pool.execute(f"""
                            INSERT INTO "{link_schema}"."{link_table}" ("{fk_col}", asset_id, is_primary)
                            VALUES ($1, $2, $3)
                            ON CONFLICT DO NOTHING
                        """, new_id, UUID(aid), is_primary)
                    except Exception:
                        pass  # Non-critical if individual link fails

            committed += 1
        except Exception as e:
            errors.append({"index": i, "error": str(e)})

    return {"ok": True, "committed": committed, "errors": errors}


@app.post("/api/inbox-commit-knowledge")
async def commit_knowledge_rows(request: Request):
    """
    Commit staged knowledge captures to markdown + files.assets.
    Body: {
        rows: [
            { topic: "pets", note: "Opal is my black cat", asset_id: "uuid", file_path: "inbox/photo.jpg" },
            ...
        ]
    }
    Returns: { ok, committed: N, errors: [...] }
    """
    body = await request.json()
    rows = body.get("rows", [])

    if not rows:
        raise HTTPException(status_code=400, detail="No rows to commit")

    committed = 0
    errors = []

    for i, row in enumerate(rows):
        topic = (row.get("topic") or "captures").strip().lower().replace(" ", "-")
        note = (row.get("note") or "").strip()
        asset_id = row.get("asset_id")
        file_path = row.get("file_path", "")

        if not note:
            errors.append({"index": i, "error": "Note is required"})
            continue

        try:
            # 1. Move the photo to /files/knowledge/<topic>/ if it's still in inbox
            photo_link = ""
            if asset_id:
                # Update the asset domain to 'knowledge'
                await pool.execute("""
                    UPDATE files.assets SET domain = 'knowledge'
                    WHERE id = $1 AND domain IS DISTINCT FROM 'knowledge'
                """, UUID(asset_id))

                # Get the asset path for the markdown link
                asset_path = await pool.fetchval(
                    "SELECT path FROM files.assets WHERE id = $1", UUID(asset_id)
                )
                if asset_path:
                    # Normalize for markdown link
                    rel_path = asset_path.replace("/files/", "").replace("/home/michael/files/", "")
                    photo_link = f" ![photo](/files/{rel_path})"

            # 2. Append to /knowledge/<topic>.md via filewriter-style direct write
            topic_path = topic.replace("/", os.sep)
            knowledge_dir = Path("/knowledge") if Path("/knowledge").exists() else FILES_ROOT.parent / "knowledge"

            # Ensure topic directory exists
            topic_file = knowledge_dir / f"{topic_path}.md"
            topic_file.parent.mkdir(parents=True, exist_ok=True)

            # Build the entry
            today = date.today().isoformat()
            entry = f"- [{today}] {note}{photo_link}\n"

            # Create file with header if it doesn't exist
            if not topic_file.exists():
                topic_title = topic.replace("-", " ").replace("/", " / ").title()
                topic_file.write_text(f"# {topic_title}\n\n{entry}")
            else:
                with open(topic_file, "a") as f:
                    f.write(entry)

            committed += 1

        except Exception as e:
            errors.append({"index": i, "error": str(e)})

    return {"ok": True, "committed": committed, "errors": errors}


@app.get("/inbox", response_class=HTMLResponse)
async def inbox_page():
    """Batch processing page for inbox files."""
    return FileResponse("static/inbox.html")


@app.get("/upload", response_class=HTMLResponse)
async def upload_page():
    """Simple mobile-friendly upload page for dropping files into /files/inbox/."""
    html = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Upload to Inbox — 595BowersHub</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f1117; color: #e1e4e8; min-height: 100vh; padding: 1rem; }
        h1 { font-size: 1.4rem; margin-bottom: 0.5rem; }
        h1 span { color: #58a6ff; }
        .subtitle { color: #8b949e; font-size: 0.85rem; margin-bottom: 1.5rem; }
        .drop-zone { border: 2px dashed #30363d; border-radius: 12px; padding: 3rem 1.5rem; text-align: center; cursor: pointer; transition: all 0.2s; margin-bottom: 1rem; }
        .drop-zone:hover, .drop-zone.dragover { border-color: #58a6ff; background: rgba(88,166,255,0.05); }
        .drop-zone .icon { font-size: 3rem; margin-bottom: 0.5rem; }
        .drop-zone p { color: #8b949e; font-size: 0.9rem; }
        .drop-zone .btn { display: inline-block; margin-top: 1rem; background: #58a6ff; color: #0f1117; padding: 0.6rem 1.5rem; border-radius: 6px; font-weight: 600; font-size: 0.9rem; }
        input[type=file] { display: none; }
        .preview-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr)); gap: 0.5rem; margin-bottom: 1rem; }
        .preview-item { position: relative; border-radius: 8px; overflow: hidden; aspect-ratio: 1; background: #161b22; border: 1px solid #30363d; }
        .preview-item img { width: 100%; height: 100%; object-fit: cover; }
        .preview-item .name { position: absolute; bottom: 0; left: 0; right: 0; background: rgba(0,0,0,0.7); padding: 0.2rem 0.4rem; font-size: 0.65rem; color: #c9d1d9; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .preview-item .remove { position: absolute; top: 4px; right: 4px; background: rgba(248,81,73,0.9); color: #fff; border: none; border-radius: 50%; width: 20px; height: 20px; font-size: 0.7rem; cursor: pointer; display: flex; align-items: center; justify-content: center; }
        .upload-btn { width: 100%; padding: 0.8rem; background: #238636; color: #fff; border: none; border-radius: 8px; font-size: 1rem; font-weight: 600; cursor: pointer; transition: background 0.2s; }
        .upload-btn:hover { background: #2ea043; }
        .upload-btn:disabled { background: #21262d; color: #484f58; cursor: not-allowed; }
        .status { margin-top: 1rem; padding: 0.8rem; border-radius: 8px; font-size: 0.85rem; display: none; }
        .status.success { display: block; background: rgba(35,134,54,0.2); border: 1px solid #238636; color: #3fb950; }
        .status.error { display: block; background: rgba(248,81,73,0.1); border: 1px solid #f85149; color: #f85149; }
        .status.uploading { display: block; background: rgba(88,166,255,0.1); border: 1px solid #58a6ff; color: #58a6ff; }
        .file-count { color: #58a6ff; font-weight: 600; margin-bottom: 0.5rem; font-size: 0.9rem; }
        .back-link { display: inline-block; margin-top: 1rem; color: #58a6ff; text-decoration: none; font-size: 0.85rem; }
        .back-link:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <h1>📸 Upload to <span>Inbox</span></h1>
    <p class="subtitle">Drop photos here to queue them for inventory capture</p>

    <div class="drop-zone" id="dropZone">
        <div class="icon">📁</div>
        <p>Tap to select photos or drag & drop</p>
        <span class="btn">Choose Files</span>
    </div>
    <input type="file" id="fileInput" multiple accept="image/*,application/pdf">

    <div class="file-count" id="fileCount"></div>
    <div class="preview-grid" id="previews"></div>

    <button class="upload-btn" id="uploadBtn" disabled>Upload to Inbox</button>
    <div class="status" id="status"></div>

    <a href="/" class="back-link">← Back to DB Admin</a>
    <div style="margin-top:0.5rem; display:flex; gap:1rem;">
        <a href="/inbox" style="color:#58a6ff; text-decoration:none; font-size:0.85rem;">📥 Inbox</a>
    </div>

    <script>
    let selectedFiles = [];

    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const previews = document.getElementById('previews');
    const uploadBtn = document.getElementById('uploadBtn');
    const status = document.getElementById('status');
    const fileCount = document.getElementById('fileCount');

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragover'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        addFiles(e.dataTransfer.files);
    });
    fileInput.addEventListener('change', () => { addFiles(fileInput.files); fileInput.value = ''; });

    function addFiles(fileList) {
        for (const f of fileList) {
            selectedFiles.push(f);
        }
        renderPreviews();
    }

    function removeFile(idx) {
        selectedFiles.splice(idx, 1);
        renderPreviews();
    }

    function renderPreviews() {
        fileCount.textContent = selectedFiles.length > 0 ? `${selectedFiles.length} file${selectedFiles.length > 1 ? 's' : ''} selected` : '';
        uploadBtn.disabled = selectedFiles.length === 0;
        previews.innerHTML = selectedFiles.map((f, i) => {
            const isImage = f.type.startsWith('image/');
            const thumb = isImage ? URL.createObjectURL(f) : '';
            return `<div class="preview-item">
                ${isImage ? `<img src="${thumb}">` : '<div style="display:flex;align-items:center;justify-content:center;height:100%;font-size:2rem">📄</div>'}
                <span class="name">${f.name}</span>
                <button class="remove" onclick="removeFile(${i})">✕</button>
            </div>`;
        }).join('');
    }

    uploadBtn.addEventListener('click', async () => {
        if (selectedFiles.length === 0) return;
        uploadBtn.disabled = true;
        status.className = 'status uploading';
        status.textContent = `Uploading ${selectedFiles.length} file${selectedFiles.length > 1 ? 's' : ''}...`;

        const formData = new FormData();
        for (const f of selectedFiles) {
            formData.append('files', f);
        }

        try {
            const resp = await fetch('/api/inbox-upload', { method: 'POST', body: formData });
            const data = await resp.json();
            if (data.ok) {
                status.className = 'status success';
                status.textContent = `✓ Uploaded ${data.uploaded} file${data.uploaded > 1 ? 's' : ''} to inbox. Ready for capture in AnythingLLM.`;
                selectedFiles = [];
                renderPreviews();
            } else {
                throw new Error(data.detail || 'Upload failed');
            }
        } catch (err) {
            status.className = 'status error';
            status.textContent = `✕ ${err.message}`;
            uploadBtn.disabled = false;
        }
    });
    </script>
</body>
</html>"""
    return HTMLResponse(content=html)


# --- HTML Routes -------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5002)
