"""
Native inventory skill — replaces the n8n webhook for /inventory command.

Behavior:
- /inventory (no args): show summary counts per table
- /inventory <table>: list rows from that inventory table with key columns
- /inventory <table> <filter>: list rows matching a search term

Returns a dict with '_display' key containing pre-formatted markdown.
"""
import logging
from typing import Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)

# Tables in the inventory schema and their display columns (ordered by importance)
INVENTORY_TABLES = {
    "tools": ["name", "brand", "condition", "current_value_estimate"],
    "router_bits": ["brand", "profile", "shank_size_in", "cutting_diameter_in", "has_bearing"],
    "saw_blades": ["brand", "name", "diameter_in", "teeth", "type", "condition"],
    "wood": ["species", "dimensions", "notes"],
    "albums": ["title", "artist", "condition"],
}

# Aliases so users can type natural names
TABLE_ALIASES = {
    "tool": "tools",
    "bits": "router_bits",
    "router bits": "router_bits",
    "routerbits": "router_bits",
    "bit": "router_bits",
    "blades": "saw_blades",
    "blade": "saw_blades",
    "saw blades": "saw_blades",
    "sawblades": "saw_blades",
    "album": "albums",
    "records": "albums",
    "vinyl": "albums",
}


def _resolve_table(name: str) -> Optional[str]:
    """Resolve a user-supplied table name to a canonical inventory table."""
    name = name.strip().lower()
    if name in INVENTORY_TABLES:
        return name
    if name in TABLE_ALIASES:
        return TABLE_ALIASES[name]
    return None


def _format_value(val, col_name: str) -> str:
    """Format a single cell value for display."""
    if val is None:
        return "—"
    if isinstance(val, bool):
        return "✓" if val else "✗"
    if isinstance(val, float):
        if "price" in col_name or "value" in col_name or "cost" in col_name:
            return f"${val:,.2f}"
        if "_in" in col_name:
            # Measurement in inches — show as fraction if common
            common_fracs = {0.125: '1/8"', 0.25: '1/4"', 0.375: '3/8"', 0.5: '1/2"',
                           0.625: '5/8"', 0.75: '3/4"', 0.875: '7/8"', 1.0: '1"',
                           1.5: '1-1/2"', 2.0: '2"'}
            if val in common_fracs:
                return common_fracs[val]
            return f'{val}"'
        return f"{val:.2f}"
    return str(val)[:60]


async def get_inventory(table: Optional[str] = None, filter_term: Optional[str] = None) -> dict:
    """
    Main entry point for the /inventory slash command.
    
    - No args: return counts per table
    - Table name: return rows from that table
    - Table + filter: search within that table
    """
    pool = get_pool()

    # No table specified — show summary
    if not table or not table.strip():
        return await _inventory_summary(pool)

    # Parse: first word is table, rest is filter
    parts = table.strip().split(None, 1)
    table_name = parts[0]
    if filter_term is None and len(parts) > 1:
        filter_term = parts[1]

    resolved = _resolve_table(table_name)
    if not resolved:
        available = ", ".join(INVENTORY_TABLES.keys())
        return {
            "_display": f"⚠️ Unknown inventory table: `{table_name}`\n\nAvailable: {available}",
            "error": f"Unknown table: {table_name}",
        }

    return await _inventory_list(pool, resolved, filter_term)


async def _inventory_summary(pool) -> dict:
    """Show counts per inventory table."""
    lines = ["**📦 Inventory Summary**\n"]
    
    async with pool.acquire() as conn:
        for table, _ in INVENTORY_TABLES.items():
            try:
                row = await conn.fetchrow(
                    f"SELECT COUNT(*) as count FROM inventory.{table} WHERE archived_at IS NULL"
                )
                count = row["count"] if row else 0
                lines.append(f"- **{table}**: {count} items")
            except Exception:
                lines.append(f"- **{table}**: (error reading)")

    lines.append("\n*Use `/inventory <table>` to see items (e.g. `/inventory tools`)*")
    return {"_display": "\n".join(lines)}


async def _inventory_list(pool, table: str, filter_term: Optional[str] = None) -> dict:
    """List rows from an inventory table as a markdown table."""
    columns = INVENTORY_TABLES.get(table, ["name"])
    
    # Always include 'name' or 'title' or 'brand' as the first identifier
    # Build SELECT with id + display columns
    # Only select columns that actually exist in the table
    async with pool.acquire() as conn:
        # Get actual column names from the table
        existing_cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'inventory' AND table_name = $1",
            table,
        )
        existing_names = {r["column_name"] for r in existing_cols}
        
        # Filter to columns that exist
        display_cols = [c for c in columns if c in existing_names]
        if not display_cols:
            display_cols = [c for c in existing_names if c not in ("id", "created_at", "updated_at", "archived_at")][:5]
        
        select_cols = ", ".join(display_cols)
        
        # Build query
        if filter_term:
            # Search across all text columns
            text_cols = [c for c in display_cols if c not in ("has_bearing",)]
            conditions = " OR ".join(f"CAST({c} AS TEXT) ILIKE $1" for c in text_cols)
            query = (
                f"SELECT {select_cols} FROM inventory.{table} "
                f"WHERE archived_at IS NULL AND ({conditions}) "
                f"ORDER BY id LIMIT 50"
            )
            rows = await conn.fetch(query, f"%{filter_term}%")
        else:
            query = (
                f"SELECT {select_cols} FROM inventory.{table} "
                f"WHERE archived_at IS NULL "
                f"ORDER BY id LIMIT 50"
            )
            rows = await conn.fetch(query)
    
    if not rows:
        if filter_term:
            return {"_display": f"No items in **{table}** matching \"{filter_term}\"."}
        return {"_display": f"**{table}** is empty."}

    # Build markdown table
    headers = display_cols
    header_labels = [h.replace("_", " ").title() for h in headers]
    
    lines = [f"**📦 {table}** ({len(rows)} items)\n"]
    lines.append("| " + " | ".join(header_labels) + " |")
    lines.append("| " + " | ".join("---" for _ in headers) + " |")
    
    for row in rows:
        values = [_format_value(row[h], h) for h in headers]
        lines.append("| " + " | ".join(values) + " |")
    
    if len(rows) == 50:
        lines.append("\n*Showing first 50 results*")
    
    if filter_term:
        lines.append(f"\n*Filtered by: \"{filter_term}\"*")
    
    return {"_display": "\n".join(lines)}
