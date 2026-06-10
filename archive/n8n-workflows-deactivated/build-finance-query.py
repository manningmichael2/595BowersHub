"""Update the Finance SQL Query (NL→SQL) workflow's schema prompt.

Dynamically queries the Postgres information_schema to build the prompt,
so new tables/columns are picked up automatically on re-run.

The prompt includes:
  - All tables in public, inventory, files, house, cook schemas
  - Column names and types for each
  - The category hierarchy and natural-language mappings (hardcoded — these
    are semantic, not derivable from schema alone)
  - Relationships between tables

Run after any schema change (new tables, new columns, new categories).
"""
import json
import subprocess

from _config import API_KEY, N8N_URL
WORKFLOW_ID = "EIinsmGcdxOYqj5c"
SCHEMAS_TO_INCLUDE = ["public", "inventory", "files", "house", "cook"]


def api(method, path, data=None):
    cmd = ["curl", "-s", "-X", method,
           "-H", f"X-N8N-API-KEY: {API_KEY}",
           "-H", "Content-Type: application/json"]
    if data is not None:
        cmd.extend(["-d", json.dumps(data)])
    cmd.append(f"{N8N_URL}/api/v1{path}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    return json.loads(r.stdout) if r.stdout else {}


def query_db(sql):
    """Run a SQL query against the finance DB via SSH + docker exec."""
    cmd = ["ssh", "hub", f"docker exec -i postgres psql -U michael -d finance -t -A -F '|' -c \"{sql}\""]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"DB query failed: {r.stderr}")
        return []
    rows = []
    for line in r.stdout.strip().split("\n"):
        if line:
            rows.append(line.split("|"))
    return rows


def build_schema_description():
    """Query information_schema and build a human-readable schema description."""
    schema_filter = ",".join(f"'{s}'" for s in SCHEMAS_TO_INCLUDE)

    # Get all tables
    tables = query_db(
        f"SELECT table_schema, table_name FROM information_schema.tables "
        f"WHERE table_schema IN ({schema_filter}) AND table_type = 'BASE TABLE' "
        f"ORDER BY table_schema, table_name"
    )

    # Get all columns
    columns = query_db(
        f"SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
        f"FROM information_schema.columns "
        f"WHERE table_schema IN ({schema_filter}) "
        f"ORDER BY table_schema, table_name, ordinal_position"
    )

    # Organize columns by schema.table
    col_map = {}
    for row in columns:
        if len(row) < 4:
            continue
        schema, table, col, dtype = row[0], row[1], row[2], row[3]
        key = f"{schema}.{table}"
        if key not in col_map:
            col_map[key] = []
        # Simplify type names
        type_map = {
            "character varying": "varchar",
            "timestamp with time zone": "timestamptz",
            "timestamp without time zone": "timestamp",
            "double precision": "float",
            "boolean": "boolean",
            "integer": "integer",
            "bigint": "bigint",
            "numeric": "numeric",
            "text": "text",
            "date": "date",
            "uuid": "uuid",
            "jsonb": "jsonb",
            "ARRAY": "array",
            "smallint": "smallint",
        }
        short_type = type_map.get(dtype, dtype)
        nullable = " nullable" if len(row) > 4 and row[4] == "YES" else ""
        col_map[key].append(f"  - {col} ({short_type}{nullable})")

    # Build output
    lines = ["DATABASE SCHEMA (auto-generated from live database):", ""]

    current_schema = None
    for row in tables:
        if len(row) < 2:
            continue
        schema, table = row[0], row[1]
        key = f"{schema}.{table}"

        if schema != current_schema:
            if current_schema is not None:
                lines.append("")
            lines.append(f"=== Schema: {schema} ===")
            lines.append("")
            current_schema = schema

        lines.append(f"Table: {schema}.{table}")
        if key in col_map:
            lines.extend(col_map[key])
        lines.append("")

    return lines


# ===================================================================
# CATEGORY HIERARCHY (semantic — can't be derived from schema alone)
# ===================================================================
category_lines = [
    "CATEGORY HIERARCHY (VERY IMPORTANT — these are the EXACT names in categories.name):",
    "",
    "Top-level categories that are PARENTS ONLY (do NOT use directly for transaction lookups):",
    "  Food, House, Transportation",
    "Use these only when aggregating across all children (e.g. 'total Food spending' = SUM where category in (Food_Groceries, Food_Dining)).",
    "",
    "LEAF categories (these are what transactions are actually assigned to):",
    "  ATM",
    "  Entertainment",
    "  Food_Dining       -- restaurants, cafes, takeout, bars",
    "  Food_Groceries    -- grocery stores, supermarkets",
    "  House_Furniture",
    "  House_Improvement",
    "  House_Maintenance",
    "  House_Mortgage",
    "  House_Utilities",
    "  Income",
    "  Insurance",
    "  Medical",
    "  Other",
    "  Shopping",
    "  Subscriptions",
    "  Trans_Car_Insurance",
    "  Trans_Car_Maintenance",
    "  Trans_Gas",
    "  Trans_Public_Transit",
    "  Transfer",
    "  Travel",
    "  Woodshop",
    "",
    "NATURAL LANGUAGE → CATEGORY MAPPING (use the EXACT leaf name, not the user's word):",
    "  'groceries', 'food shopping', 'supermarket'    → Food_Groceries",
    "  'dining', 'eating out', 'restaurants', 'food'  → Food_Dining (when context is meals out)",
    "  'gas', 'fuel', 'gasoline'                      → Trans_Gas",
    "  'car insurance', 'auto insurance'              → Trans_Car_Insurance",
    "  'car maintenance', 'oil change', 'car repair'  → Trans_Car_Maintenance",
    "  'public transit', 'bus', 'train', 'subway'    → Trans_Public_Transit",
    "  'mortgage', 'house payment'                    → House_Mortgage",
    "  'utilities', 'electric', 'water', 'gas bill'  → House_Utilities",
    "  'home repair', 'plumber', 'handyman'           → House_Maintenance",
    "  'renovation', 'remodel', 'home improvement'    → House_Improvement",
    "  'furniture'                                    → House_Furniture",
    "  'subscriptions', 'recurring', 'streaming'      → Subscriptions",
    "  'doctor', 'medical', 'pharmacy', 'dentist'    → Medical",
    "",
    "  When the user says 'food' generically (could mean groceries OR dining), prefer to",
    "  return BOTH categories grouped, e.g. GROUP BY c.name. Don't guess.",
    "",
    "PARENT ROLLUPS (when user asks for total spending in a parent category):",
    "  Use a parent-id subquery so the query auto-adapts if leaves are added later:",
    "    WHERE c.parent_id = (SELECT id FROM categories WHERE name = 'Food')",
    "  Apply this for parents: Food, House, Transportation.",
]

# ===================================================================
# QUERY RULES
# ===================================================================
rules_lines = [
    "",
    "IMPORTANT QUERY RULES:",
    "- This is READ-ONLY. Generate only SELECT statements.",
    "- Amounts in public.transactions are NEGATIVE for spending, POSITIVE for income.",
    "- Spending totals: use ABS(SUM(amount)) or SUM(-amount) to return positive numbers.",
    "- Always exclude transfers when calculating spending: WHERE is_transfer = false.",
    "- Use EXACT category names from the leaf list above. Match with c.name = 'Food_Groceries'. Do NOT use LIKE patterns.",
    "- Use aggregation (SUM, COUNT, AVG, GROUP BY) for totals/summaries.",
    "- Only return individual rows when user explicitly wants a list.",
    "- Always JOIN with relevant tables for readable output (e.g., account names, category names).",
    "- For inventory queries: archived_at IS NULL means active records. Include this filter unless user asks about archived items.",
    "- For file/image queries: join through _files link tables to files.assets.",
    "- Add LIMIT 5000 as safety cap.",
    "- Today is: %TODAY%",
]


def main():
    print("Querying database schema...")
    schema_lines = build_schema_description()
    print(f"  Found {len(schema_lines)} lines of schema description")

    # Combine all prompt sections
    all_lines = schema_lines + [""] + category_lines + rules_lines

    # Build the Prepare Prompt Code node
    prepare_prompt_code = (
        "const body = $input.first().json.body || $input.first().json;\n"
        "const question = body.question || '';\n\n"
        "if (!question || question.trim().length === 0) {\n"
        "  return [{ json: { error: 'No question provided. Send {\"question\": \"your question here\"}', valid: false } }];\n"
        "}\n\n"
        "const today = new Date().toISOString().split('T')[0];\n\n"
        "const schema = ["
        + ", ".join(json.dumps(line) for line in all_lines)
        + "].join('\\n').replace('%TODAY%', today);\n\n"
        "return [{ json: { question, schema, valid: true } }];"
    )

    # Pull current workflow
    current = api("GET", f"/workflows/{WORKFLOW_ID}")
    if "nodes" not in current:
        print("Failed to load workflow:", current)
        raise SystemExit(1)

    # Update the Prepare Prompt node
    updated = False
    for node in current["nodes"]:
        if node["name"] == "Prepare Prompt":
            node["parameters"]["jsCode"] = prepare_prompt_code
            updated = True
            break

    if not updated:
        print("Could not find 'Prepare Prompt' node!")
        raise SystemExit(1)

    # Update the Haiku prompt to mention all schemas
    for node in current["nodes"]:
        if node["name"] == "Generate SQL (Haiku)":
            node["parameters"]["jsonBody"] = (
                "={{ JSON.stringify({ "
                "model: 'claude-haiku-4-5-20251001', "
                "max_tokens: 1024, "
                "messages: [{ role: 'user', content: "
                "$('Prepare Prompt').first().json.schema + "
                "'\\n\\nUSER QUESTION: ' + "
                "$('Prepare Prompt').first().json.question + "
                "'\\n\\nGenerate a single PostgreSQL SELECT query to answer this question. "
                "Return ONLY the SQL query, no explanation, no markdown, no code fences. "
                "The database has multiple schemas (public, inventory, files, house, cook). "
                "Always use fully-qualified table names (schema.table). "
                "When the question references categories, use the EXACT leaf category names from the schema "
                "(e.g. Food_Groceries, Trans_Gas, House_Mortgage). Do NOT abbreviate or rephrase them. "
                "Match category names exactly with equals, never LIKE patterns. "
                "For inventory questions, filter WHERE archived_at IS NULL unless user asks about archived items. "
                "Use aggregation when appropriate. Always include LIMIT 5000.' "
                "}] }) }}"
            )
            break

    # Save a local snapshot
    with open("/home/michael/KiroProject/n8n-workflows/finance-query.json", "w") as f:
        json.dump(current, f, indent=2)
    print("Saved local snapshot to finance-query.json")

    # PUT it back
    payload = {k: current[k] for k in ["name", "nodes", "connections", "settings"]}
    resp = api("PUT", f"/workflows/{WORKFLOW_ID}", payload)
    print(f"Updated: {resp.get('name')} active={resp.get('active')}")
    if "message" in resp and not resp.get("name"):
        print(f"Error: {resp['message'][:500]}")


if __name__ == "__main__":
    main()
