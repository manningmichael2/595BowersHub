"""
Native inventory-admin skill — replaces the n8n Inventory Admin workflow.

Actions: update, archive, unarchive, delete, merge, add_column, list_columns.
All operate on tables in the `inventory` schema.
"""
import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)

ALLOWED_TABLES = {"tools", "router_bits", "saw_blades", "wood", "albums", "manuals"}

ALLOWED_COLUMN_TYPES = {
    "text": "TEXT",
    "integer": "INTEGER",
    "decimal": "NUMERIC",
    "number": "NUMERIC",
    "boolean": "BOOLEAN",
    "date": "DATE",
    "timestamp": "TIMESTAMPTZ",
}


def _validate_table(table: str) -> Optional[str]:
    """Validate table name. Returns error message or None."""
    if not table:
        return "Missing `table` parameter."
    if table not in ALLOWED_TABLES:
        return f"Unknown table: '{table}'. Valid: {', '.join(sorted(ALLOWED_TABLES))}"
    return None


def _cast_value(value: Any, col_name: str) -> Any:
    """Cast a value to the appropriate Python type for asyncpg."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        low = value.lower().strip()
        # Boolean detection
        if col_name.startswith("has_") or col_name.startswith("is_"):
            if low in ("true", "yes", "1", "y"):
                return True
            if low in ("false", "no", "0", "n"):
                return False
        # Numeric detection for known patterns
        if "_in" in col_name or "price" in col_name or "value" in col_name or "amount" in col_name or "amps" in col_name:
            try:
                # Handle fractions like "3/8"
                if "/" in value and '"' not in value:
                    parts = value.split("/")
                    if len(parts) == 2:
                        return float(Decimal(parts[0]) / Decimal(parts[1]))
                return float(Decimal(value.replace("$", "").replace(",", "")))
            except (InvalidOperation, ValueError):
                pass
    return value


async def inventory_admin(
    action: str,
    table: str,
    id: Optional[int] = None,
    fields: Optional[Dict[str, Any]] = None,
    merge_into_id: Optional[int] = None,
    column_name: Optional[str] = None,
    column_type: Optional[str] = None,
) -> dict:
    """
    Main entry point for inventory admin operations.
    """
    if not action:
        return {"error": "Missing `action`. One of: update, archive, unarchive, delete, merge, add_column, list_columns."}
    
    action = action.strip().lower()
    table = (table or "").strip().lower()
    
    err = _validate_table(table)
    if err and action not in ("list_columns",):
        # list_columns is allowed without a valid table (shows all)
        if action != "list_columns":
            return {"error": err, "_display": f"⚠️ {err}"}

    if action == "update":
        return await _update(table, id, fields)
    elif action == "archive":
        return await _archive(table, id)
    elif action == "unarchive":
        return await _unarchive(table, id)
    elif action == "delete":
        return await _delete(table, id)
    elif action == "merge":
        return await _merge(table, id, merge_into_id, fields)
    elif action == "add_column":
        return await _add_column(table, column_name, column_type)
    elif action == "list_columns":
        return await _list_columns(table)
    else:
        return {"error": f"Unknown action: '{action}'. Valid: update, archive, unarchive, delete, merge, add_column, list_columns."}


async def _update(table: str, record_id: Optional[int], fields: Optional[Dict[str, Any]]) -> dict:
    """Update fields on an inventory record."""
    if not record_id:
        return {"error": "Missing `id` for update.", "_display": "⚠️ Provide the record ID to update."}
    if not fields or not isinstance(fields, dict) or len(fields) == 0:
        return {"error": "Missing `fields` for update.", "_display": "⚠️ Provide fields to update as a dict."}

    pool = get_pool()
    async with pool.acquire() as conn:
        # Verify record exists
        row = await conn.fetchrow(f"SELECT id FROM inventory.{table} WHERE id = $1", record_id)
        if not row:
            return {"error": f"Record {record_id} not found in {table}.", "_display": f"⚠️ No record with id={record_id} in `{table}`."}

        # Get existing columns
        existing = await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'inventory' AND table_name = $1",
            table,
        )
        existing_names = {r["column_name"] for r in existing}

        # Filter to valid columns and build SET clause
        set_parts = []
        values = []
        i = 1
        for col, val in fields.items():
            col = col.strip().lower().replace(" ", "_")
            if col in ("id", "created_at"):
                continue  # Never update these
            if col not in existing_names:
                continue  # Skip unknown columns silently
            values.append(_cast_value(val, col))
            set_parts.append(f"{col} = ${i + 1}")
            i += 1

        if not set_parts:
            return {"error": "No valid fields to update.", "_display": "⚠️ None of the provided fields exist on this table."}

        # Always bump updated_at if it exists
        if "updated_at" in existing_names:
            set_parts.append(f"updated_at = NOW()")

        query = f"UPDATE inventory.{table} SET {', '.join(set_parts)} WHERE id = $1"
        await conn.execute(query, record_id, *values)

    updated_fields = list(fields.keys())
    return {
        "success": True,
        "action": "update",
        "table": table,
        "id": record_id,
        "fields_updated": updated_fields,
        "_display": f"✅ Updated `{table}` #{record_id}: {', '.join(updated_fields)}",
    }


async def _archive(table: str, record_id: Optional[int]) -> dict:
    """Soft-delete by setting archived_at."""
    if not record_id:
        return {"error": "Missing `id` for archive.", "_display": "⚠️ Provide the record ID to archive."}

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE inventory.{table} SET archived_at = NOW() WHERE id = $1 AND archived_at IS NULL",
            record_id,
        )
    
    if "UPDATE 0" in result:
        return {"error": f"Record {record_id} not found or already archived.", "_display": f"⚠️ Record #{record_id} not found or already archived."}

    return {
        "success": True,
        "action": "archive",
        "table": table,
        "id": record_id,
        "_display": f"✅ Archived `{table}` #{record_id}",
    }


async def _unarchive(table: str, record_id: Optional[int]) -> dict:
    """Restore a soft-deleted record."""
    if not record_id:
        return {"error": "Missing `id` for unarchive."}

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            f"UPDATE inventory.{table} SET archived_at = NULL WHERE id = $1 AND archived_at IS NOT NULL",
            record_id,
        )
    
    if "UPDATE 0" in result:
        return {"error": f"Record {record_id} not found or not archived."}

    return {
        "success": True,
        "action": "unarchive",
        "table": table,
        "id": record_id,
        "_display": f"✅ Restored `{table}` #{record_id}",
    }


async def _delete(table: str, record_id: Optional[int]) -> dict:
    """Hard delete a record (and its file links via CASCADE)."""
    if not record_id:
        return {"error": "Missing `id` for delete."}

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(f"DELETE FROM inventory.{table} WHERE id = $1", record_id)
    
    if "DELETE 0" in result:
        return {"error": f"Record {record_id} not found in {table}."}

    return {
        "success": True,
        "action": "delete",
        "table": table,
        "id": record_id,
        "_display": f"✅ Deleted `{table}` #{record_id}",
    }


async def _merge(table: str, source_id: Optional[int], target_id: Optional[int], fields: Optional[Dict[str, Any]]) -> dict:
    """Merge source record into target (move file links, delete source)."""
    if not source_id or not target_id:
        return {"error": "Both `id` (source) and `merge_into_id` (target) are required for merge."}
    if source_id == target_id:
        return {"error": "Cannot merge a record into itself."}

    pool = get_pool()
    # Determine the files link table name
    files_table = f"{table[:-1]}_files" if table.endswith("s") else f"{table}_files"
    # router_bits → router_bit_files
    if table == "router_bits":
        files_table = "router_bit_files"

    async with pool.acquire() as conn:
        # Verify both records exist
        source = await conn.fetchrow(f"SELECT id FROM inventory.{table} WHERE id = $1", source_id)
        target = await conn.fetchrow(f"SELECT id FROM inventory.{table} WHERE id = $1", target_id)
        if not source:
            return {"error": f"Source record {source_id} not found."}
        if not target:
            return {"error": f"Target record {target_id} not found."}

        # Move file links from source to target
        id_col = f"{table[:-1]}_id" if table.endswith("s") else f"{table}_id"
        if table == "router_bits":
            id_col = "router_bit_id"
        
        try:
            await conn.execute(
                f"UPDATE inventory.{files_table} SET {id_col} = $1 WHERE {id_col} = $2",
                target_id, source_id,
            )
        except Exception:
            pass  # Files table may not exist or have different schema

        # If fields provided, update target with them
        if fields and isinstance(fields, dict):
            set_parts = []
            values = [target_id]
            i = 2
            for col, val in fields.items():
                col = col.strip().lower()
                if col in ("id", "created_at"):
                    continue
                values.append(_cast_value(val, col))
                set_parts.append(f"{col} = ${i}")
                i += 1
            if set_parts:
                await conn.execute(
                    f"UPDATE inventory.{table} SET {', '.join(set_parts)} WHERE id = $1",
                    *values,
                )

        # Delete source
        await conn.execute(f"DELETE FROM inventory.{table} WHERE id = $1", source_id)

    return {
        "success": True,
        "action": "merge",
        "table": table,
        "source_id": source_id,
        "target_id": target_id,
        "_display": f"✅ Merged `{table}` #{source_id} into #{target_id} (source deleted, files moved)",
    }


async def _add_column(table: str, column_name: Optional[str], column_type: Optional[str]) -> dict:
    """Add a new column to an inventory table."""
    if not column_name:
        return {"error": "Missing `column_name`."}
    
    col = column_name.strip().lower().replace(" ", "_")
    col_type = (column_type or "text").strip().lower()
    
    if col_type not in ALLOWED_COLUMN_TYPES:
        return {"error": f"Unknown column type: '{col_type}'. Valid: {', '.join(ALLOWED_COLUMN_TYPES.keys())}"}

    pg_type = ALLOWED_COLUMN_TYPES[col_type]

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check if column already exists
        existing = await conn.fetchrow(
            "SELECT 1 FROM information_schema.columns WHERE table_schema = 'inventory' AND table_name = $1 AND column_name = $2",
            table, col,
        )
        if existing:
            return {"error": f"Column '{col}' already exists on {table}.", "_display": f"⚠️ Column `{col}` already exists on `{table}`."}

        await conn.execute(f"ALTER TABLE inventory.{table} ADD COLUMN {col} {pg_type}")

    return {
        "success": True,
        "action": "add_column",
        "table": table,
        "column_name": col,
        "column_type": pg_type,
        "_display": f"✅ Added column `{col}` ({pg_type}) to `inventory.{table}`",
    }


async def _list_columns(table: str) -> dict:
    """List all columns on an inventory table."""
    if not table:
        table_list = sorted(ALLOWED_TABLES)
    else:
        table_list = [table]

    pool = get_pool()
    results = {}
    
    async with pool.acquire() as conn:
        for t in table_list:
            cols = await conn.fetch(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'inventory' AND table_name = $1 ORDER BY ordinal_position",
                t,
            )
            results[t] = [{"name": c["column_name"], "type": c["data_type"]} for c in cols]

    lines = ["**📋 Inventory Columns**\n"]
    for t, cols in results.items():
        lines.append(f"\n**{t}** ({len(cols)} columns)")
        for c in cols:
            lines.append(f"- `{c['name']}` ({c['type']})")

    return {
        "columns": results,
        "_display": "\n".join(lines),
    }
