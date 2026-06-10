"""
Build the 'Inventory Admin' n8n workflow.

Single webhook:
  POST /webhook/inventory-admin
       Inputs:  { action, table, id?, fields?, merge_into_id? }
       Output:  { ok, action, table, id?, message, record? }

Actions:
  - update:    SET fields on inventory.<table> WHERE id = <id>
  - archive:   SET archived_at = now() WHERE id = <id>
  - unarchive: SET archived_at = NULL WHERE id = <id>
  - delete:    DELETE FROM inventory.<table> WHERE id = <id> (+ cascade files)
  - merge:     Copy non-null fields from <id> into <merge_into_id>,
               reassign file links, then delete <id>

Covers tables: tools, saw_blades, wood, albums, manuals, router_bits.

Idempotent — safe to re-run. Updates existing workflow if found by name.
"""
import json
import subprocess
import sys

from _config import API_KEY, N8N_URL
POSTGRES_CRED_ID = "JvthRCvWKXaGGbBI"

# ===================================================================
# CODE NODES
# ===================================================================

validate_code = r"""
const body = $input.first().json.body || $input.first().json;
const action = (body.action || "").trim().toLowerCase();
const table = (body.table || "").trim().toLowerCase();
const id = Number(body.id) || 0;
const mergeIntoId = Number(body.merge_into_id) || 0;
const fields = body.fields || {};
const columnName = (body.column_name || "").trim().toLowerCase().replace(/\s+/g, '_');
const columnType = (body.column_type || "text").trim().toLowerCase();

const VALID_ACTIONS = ["update", "archive", "unarchive", "delete", "merge", "add_column", "list_columns"];
const VALID_TABLES = ["tools", "saw_blades", "wood", "albums", "manuals", "router_bits"];
const VALID_COL_TYPES = ["text", "number", "integer", "decimal", "boolean", "date", "timestamp"];

if (!VALID_ACTIONS.includes(action)) {
  throw new Error(`Invalid action '${action}'. Must be one of: ${VALID_ACTIONS.join(", ")}`);
}
if (!VALID_TABLES.includes(table)) {
  throw new Error(`Invalid table '${table}'. Must be one of: ${VALID_TABLES.join(", ")}`);
}
if (["update", "archive", "unarchive", "delete"].includes(action) && !id) {
  throw new Error(`Action '${action}' requires a numeric 'id'.`);
}
if (action === "update" && (!fields || typeof fields !== "object" || Object.keys(fields).length === 0)) {
  throw new Error("Action 'update' requires a non-empty 'fields' object.");
}
if (action === "merge" && (!id || !mergeIntoId)) {
  throw new Error("Action 'merge' requires both 'id' (source to remove) and 'merge_into_id' (target to keep).");
}
if (action === "merge" && id === mergeIntoId) {
  throw new Error("Cannot merge a record into itself.");
}
if (action === "add_column") {
  if (!columnName) throw new Error("Action 'add_column' requires 'column_name'.");
  if (!columnName.replace(/_/g, '').match(/^[a-z0-9]+$/)) {
    throw new Error("column_name must be lowercase alphanumeric with underscores only.");
  }
  if (columnName.length > 63) throw new Error("column_name too long (max 63 chars).");
  if (!VALID_COL_TYPES.includes(columnType)) {
    throw new Error(`Invalid column_type '${columnType}'. Must be one of: ${VALID_COL_TYPES.join(", ")}`);
  }
}

return [{
  json: { action, table, id, merge_into_id: mergeIntoId, fields, column_name: columnName, column_type: columnType }
}];
"""

build_sql_code = r"""
const ctx = $json;
const { action, table, id, merge_into_id, fields } = ctx;

// Column whitelist per table to prevent injection
// MUST match actual DB columns (excluding id, created_at, updated_at, archived_at)
const TABLE_COLUMNS = {
  tools: ["name", "brand", "model", "type", "notes", "acquired_at"],
  saw_blades: ["brand", "diameter_in", "teeth", "kerf_in", "type", "notes", "acquired_at"],
  wood: ["species", "dimensions", "quantity", "unit", "notes", "acquired_at"],
  albums: ["title", "artist", "label", "catalog_number", "year", "condition", "notes", "last_played_at"],
  manuals: ["title", "brand", "model", "doc_type", "notes"],
  router_bits: ["brand", "profile", "shank_size_in", "cutting_diameter_in", "cutting_length_in", "has_bearing", "set_name", "notes", "condition", "purchase_price", "current_value_estimate", "value_estimated_at"],
};

// File link table names
const FILE_TABLES = {
  tools: "inventory.tool_files",
  saw_blades: "inventory.saw_blade_files",
  wood: "inventory.wood_files",
  albums: "inventory.album_files",
  manuals: "inventory.manual_files",
  router_bits: "inventory.router_bit_files",
};

// FK column in the file link table
const FK_COLUMNS = {
  tools: "tool_id",
  saw_blades: "saw_blade_id",
  wood: "wood_id",
  albums: "album_id",
  manuals: "manual_id",
  router_bits: "router_bit_id",
};

function sqlStr(v) {
  if (v === null || v === undefined || v === "") return "NULL";
  return "'" + String(v).replace(/'/g, "''") + "'";
}

function sqlVal(col, v) {
  if (v === null || v === undefined || v === "") return "NULL";
  // Boolean values
  if (v === true || v === false || v === "true" || v === "false") {
    return (v === true || v === "true") ? "true" : "false";
  }
  // Known numeric columns (legacy list)
  const numCols = ["diameter_in", "teeth", "kerf_in", "quantity", "year",
    "shank_size_in", "cutting_diameter_in", "cutting_length_in",
    "purchase_price", "current_value_estimate", "floor"];
  if (numCols.includes(col)) {
    const n = Number(v);
    return Number.isFinite(n) ? String(n) : "NULL";
  }
  // Heuristic: columns ending in _in, _mm, _lbs, _amps, _rpm, _deg, _watts, _volts
  // or containing 'price', 'cost', 'weight', 'count' are likely numeric
  if (/_(in|mm|lbs|kg|amps|rpm|deg|watts|volts|oz)$/.test(col) ||
      /^(price|cost|weight|count|rating|quantity|motor|voltage|wattage)/.test(col)) {
    const n = Number(v);
    if (Number.isFinite(n)) return String(n);
  }
  // Boolean columns (has_* pattern)
  if (col.startsWith("has_") || col.startsWith("is_")) {
    return v === true || v === "true" || v === "yes" ? "true" : "false";
  }
  // Date columns
  if (col.endsWith("_at") || col === "acquired_at") {
    return sqlStr(v);
  }
  // If the value looks like a pure number, treat it as numeric
  if (typeof v === "number" || (typeof v === "string" && /^-?\d+(\.\d+)?$/.test(v.trim()))) {
    const n = Number(v);
    if (Number.isFinite(n)) return String(n);
  }
  return sqlStr(v);
}

const fullTable = `inventory.${table}`;
const fileTable = FILE_TABLES[table];
const fkCol = FK_COLUMNS[table];
const allowedCols = TABLE_COLUMNS[table] || [];

let sql = "";
let description = "";

if (action === "update") {
  // Accept any column that's in the whitelist OR any column name that looks valid
  // (alphanumeric + underscores). This allows updating dynamically-added columns.
  // The DB will reject truly invalid column names with a clear error.
  const setClauses = [];
  for (const [col, val] of Object.entries(fields)) {
    // Skip system columns that should never be manually set
    if (["id", "created_at", "updated_at", "archived_at"].includes(col)) continue;
    // Validate column name format (prevent injection)
    if (!/^[a-z][a-z0-9_]*$/.test(col)) continue;
    setClauses.push(`"${col}" = ${sqlVal(col, val)}`);
  }
  if (setClauses.length === 0) {
    throw new Error(`No valid columns to update. Provide field names as lowercase alphanumeric with underscores.`);
  }
  setClauses.push("updated_at = now()");
  sql = `UPDATE ${fullTable} SET ${setClauses.join(", ")} WHERE id = ${id} RETURNING *;`;
  description = `Updated ${setClauses.length - 1} field(s) on ${table} #${id}`;

} else if (action === "archive") {
  sql = `UPDATE ${fullTable} SET archived_at = now(), updated_at = now() WHERE id = ${id} RETURNING id, archived_at;`;
  description = `Archived ${table} #${id}`;

} else if (action === "unarchive") {
  sql = `UPDATE ${fullTable} SET archived_at = NULL, updated_at = now() WHERE id = ${id} RETURNING id, archived_at;`;
  description = `Unarchived ${table} #${id}`;

} else if (action === "delete") {
  // CASCADE on FK handles file links automatically
  sql = `DELETE FROM ${fullTable} WHERE id = ${id} RETURNING id;`;
  description = `Deleted ${table} #${id} (file links cascaded)`;

} else if (action === "merge") {
  // 1. Reassign file links from source to target (ignore conflicts)
  // 2. Copy non-null fields from source into target where target is null
  // 3. Delete source
  sql = [
    `-- Reassign file links from #${id} to #${merge_into_id}`,
    `UPDATE ${fileTable} SET ${fkCol} = ${merge_into_id} WHERE ${fkCol} = ${id} AND NOT EXISTS (SELECT 1 FROM ${fileTable} f2 WHERE f2.${fkCol} = ${merge_into_id} AND f2.asset_id = ${fileTable}.asset_id);`,
    `-- Delete any remaining file links on source (duplicates that couldn't move)`,
    `DELETE FROM ${fileTable} WHERE ${fkCol} = ${id};`,
    `-- Merge: fill nulls in target from source`,
    `UPDATE ${fullTable} AS target SET ${allowedCols.map(c => `${c} = COALESCE(target.${c}, source.${c})`).join(", ")}, updated_at = now() FROM ${fullTable} AS source WHERE target.id = ${merge_into_id} AND source.id = ${id};`,
    `-- Delete source record`,
    `DELETE FROM ${fullTable} WHERE id = ${id};`,
    `-- Return merged record`,
    `SELECT * FROM ${fullTable} WHERE id = ${merge_into_id};`,
  ].join("\n");
  description = `Merged ${table} #${id} into #${merge_into_id}`;

} else if (action === "list_columns") {
  sql = `SELECT column_name, data_type, is_nullable FROM information_schema.columns WHERE table_schema = 'inventory' AND table_name = '${table}' ORDER BY ordinal_position;`;
  description = `Listed columns for inventory.${table}`;

} else if (action === "add_column") {
  const COL_TYPE_MAP = {
    text: "TEXT",
    number: "NUMERIC",
    integer: "BIGINT",
    decimal: "NUMERIC(10,2)",
    boolean: "BOOLEAN",
    date: "DATE",
    timestamp: "TIMESTAMPTZ",
  };
  const pgType = COL_TYPE_MAP[ctx.column_type] || "TEXT";
  sql = `ALTER TABLE ${fullTable} ADD COLUMN IF NOT EXISTS "${ctx.column_name}" ${pgType}; SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'inventory' AND table_name = '${table}' AND column_name = '${ctx.column_name}';`;
  description = `Added column '${ctx.column_name}' (${pgType}) to ${fullTable}`;
}

return [{ json: { ...ctx, sql, description } }];
"""

format_response_code = r"""
const ctx = $('Build SQL').first().json;
const rows = $input.all().map(i => i.json);
const record = rows.length > 0 ? rows[rows.length - 1] : null;

// For list_columns, return the full column list
if (ctx.action === "list_columns") {
  return [{ json: {
    ok: true,
    action: ctx.action,
    table: ctx.table,
    message: ctx.description,
    columns: rows.map(r => ({ name: r.column_name, type: r.data_type, nullable: r.is_nullable === 'YES' })),
  } }];
}

// For add_column, confirm what was added
if (ctx.action === "add_column") {
  return [{ json: {
    ok: true,
    action: ctx.action,
    table: ctx.table,
    column_name: ctx.column_name,
    column_type: ctx.column_type,
    message: ctx.description,
  } }];
}

return [{ json: {
  ok: true,
  action: ctx.action,
  table: ctx.table,
  id: ctx.id || null,
  merge_into_id: ctx.merge_into_id || null,
  message: ctx.description,
  record: record && record.id ? record : null,
} }];
"""

# ===================================================================
# WORKFLOW DEFINITION
# ===================================================================
pg = {"postgres": {"id": POSTGRES_CRED_ID, "name": "Finance Postgres"}}

workflow = {
    "name": "Inventory Admin",
    "nodes": [
        {
            "parameters": {
                "path": "inventory-admin",
                "httpMethod": "POST",
                "responseMode": "lastNode",
                "options": {},
            },
            "id": "n-wh",
            "name": "Webhook",
            "type": "n8n-nodes-base.webhook",
            "typeVersion": 2.1,
            "position": [200, 300],
            "webhookId": "inventory-admin",
        },
        {
            "parameters": {"jsCode": validate_code},
            "id": "n-validate",
            "name": "Validate",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [400, 300],
        },
        {
            "parameters": {"jsCode": build_sql_code},
            "id": "n-build-sql",
            "name": "Build SQL",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [600, 300],
        },
        {
            "parameters": {
                "operation": "executeQuery",
                "query": "={{ $json.sql }}",
                "options": {},
            },
            "id": "n-exec",
            "name": "Execute SQL",
            "type": "n8n-nodes-base.postgres",
            "typeVersion": 2.4,
            "position": [800, 300],
            "credentials": pg,
            "alwaysOutputData": True,
        },
        {
            "parameters": {"jsCode": format_response_code},
            "id": "n-format",
            "name": "Format Response",
            "type": "n8n-nodes-base.code",
            "typeVersion": 2,
            "position": [1000, 300],
        },
    ],
    "connections": {
        "Webhook": {"main": [[{"node": "Validate", "type": "main", "index": 0}]]},
        "Validate": {"main": [[{"node": "Build SQL", "type": "main", "index": 0}]]},
        "Build SQL": {"main": [[{"node": "Execute SQL", "type": "main", "index": 0}]]},
        "Execute SQL": {"main": [[{"node": "Format Response", "type": "main", "index": 0}]]},
    },
    "settings": {"executionOrder": "v1"},
}

# ===================================================================
# DEPLOY
# ===================================================================

def api(method, path, data=None):
    cmd = [
        "curl", "-s", "-X", method,
        f"{N8N_URL}/api/v1{path}",
        "-H", f"X-N8N-API-KEY: {API_KEY}",
        "-H", "Content-Type: application/json",
    ]
    if data:
        cmd += ["-d", json.dumps(data)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"curl failed: {result.stderr}", file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def find_workflow_by_name(name):
    resp = api("GET", "/workflows?limit=100")
    for wf in resp.get("data", []):
        if wf["name"] == name:
            return wf["id"]
    return None


def main():
    name = workflow["name"]
    existing_id = find_workflow_by_name(name)

    if existing_id:
        print(f"Found existing workflow '{name}' (id={existing_id}). Updating...")
        resp = api("PUT", f"/workflows/{existing_id}", workflow)
        if "id" not in resp:
            print(f"ERROR: {json.dumps(resp, indent=2)}", file=sys.stderr)
            sys.exit(1)
        wf_id = resp["id"]
        # Activate
        api("POST", f"/workflows/{wf_id}/activate")
        print(f"Updated and activated: {wf_id}")
    else:
        print(f"Creating new workflow '{name}'...")
        resp = api("POST", "/workflows", workflow)
        if "id" not in resp:
            print(f"ERROR: {json.dumps(resp, indent=2)}", file=sys.stderr)
            sys.exit(1)
        wf_id = resp["id"]
        # Activate
        api("POST", f"/workflows/{wf_id}/activate")
        print(f"Created and activated: {wf_id}")

    print(f"\nWebhook: POST {N8N_URL}/webhook/inventory-admin")
    print("Done.")


if __name__ == "__main__":
    main()
