"""
Native finance skills — replaces n8n webhooks for balances, filter-transactions,
spending-summary, and ask-db (NL→SQL).

All return dict with optional '_display' key containing pre-formatted markdown.
"""
import json
from backend.services.model_catalog import resolve_role
import logging
import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx
from backend.http_client import get_http_client

from backend.database import get_pool
from backend.services.sql_guard import validate_select

logger = logging.getLogger(__name__)


# =========================================================================
# get-balances — list all account balances + net worth
# =========================================================================

async def get_balances() -> dict:
    """Return all account balances grouped by org with assets/liabilities/net worth.

    Net worth is computed by the consolidated account_type-driven service
    (services/accounting/networth.py) — this preserves the skill's response
    contract while fixing classification (R3.1/R3.4)."""
    from backend.services.accounting.networth import compute_net_worth
    pool = get_pool()
    async with pool.acquire() as conn:
        nw = await compute_net_worth(conn)

    accounts = nw["accounts"]
    if not accounts:
        return {"_display": "No accounts found.", "accounts": []}

    assets = nw["assets"]
    liabilities = nw["liabilities"]
    net_worth = nw["net_worth"]

    # Build display
    lines = ["**💰 Account Balances**\n"]
    
    # Group by org
    by_org: Dict[str, List[dict]] = {}
    for a in accounts:
        by_org.setdefault(a["org"] or "(Unknown)", []).append(a)
    
    for org, accts in sorted(by_org.items()):
        lines.append(f"\n**{org}**")
        for a in accts:
            sign = "" if a["balance"] >= 0 else "-"
            lines.append(f"- {a['name']}: {sign}${abs(a['balance']):,.2f}")

    lines.append(f"\n---")
    lines.append(f"**Total Assets:** ${float(assets):,.2f}")
    lines.append(f"**Total Liabilities:** -${abs(float(liabilities)):,.2f}")
    lines.append(f"**Net Worth:** ${float(net_worth):,.2f}")

    return {
        "_display": "\n".join(lines),
        "accounts": accounts,
        "assets": float(assets),
        "liabilities": float(liabilities),
        "net_worth": float(net_worth),
    }


# =========================================================================
# filter-transactions — search by account/category/amount/description
# =========================================================================

async def filter_transactions(
    account: Optional[str] = None,
    category: Optional[str] = None,
    description: Optional[str] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = 50,
) -> dict:
    """Filter transactions by any combination of fields."""
    pool = get_pool()
    
    conditions = ["t.is_transfer = false"]
    params: List[Any] = []
    
    if account:
        params.append(f"%{account}%")
        conditions.append(f"a.account_name ILIKE ${len(params)}")
    if category:
        if category.lower() in ("uncategorized", "uncat", "none"):
            conditions.append("t.category_id IS NULL")
        else:
            params.append(f"%{category}%")
            conditions.append(f"c.name ILIKE ${len(params)}")
    if description:
        params.append(f"%{description}%")
        conditions.append(f"t.description ILIKE ${len(params)}")
    if min_amount is not None:
        params.append(min_amount)
        conditions.append(f"ABS(t.amount) >= ${len(params)}")
    if max_amount is not None:
        params.append(max_amount)
        conditions.append(f"ABS(t.amount) <= ${len(params)}")
    if start_date:
        try:
            params.append(date.fromisoformat(start_date))
            conditions.append(f"t.posted_date >= ${len(params)}")
        except ValueError:
            pass
    if end_date:
        try:
            params.append(date.fromisoformat(end_date))
            conditions.append(f"t.posted_date <= ${len(params)}")
        except ValueError:
            pass
    
    where = " AND ".join(conditions)
    params.append(limit)
    
    query = f"""
        SELECT t.posted_date, t.description, t.amount, c.name as category,
               a.account_name as account
        FROM finance.transactions t
        LEFT JOIN finance.categories c ON c.id = t.category_id
        LEFT JOIN finance.accounts a ON a.id = t.account_id
        WHERE {where}
        ORDER BY t.posted_date DESC, t.id DESC
        LIMIT ${len(params)}
    """
    
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *params)
    
    if not rows:
        return {"_display": "No matching transactions.", "transactions": []}

    total = sum(float(r["amount"]) for r in rows)
    
    lines = [f"**💳 Filtered Transactions** ({len(rows)} results)", ""]
    for r in rows:
        d = r["posted_date"].strftime("%m/%d") if r["posted_date"] else "—"
        desc = str(r["description"] or "—")[:45]
        amt = float(r["amount"])
        amt_str = f"+${amt:,.2f}" if amt >= 0 else f"-${abs(amt):,.2f}"
        cat = str(r["category"] or "").replace("_", " ")
        acct = str(r["account"] or "")[:20]
        cat_str = f" · {cat}" if cat else ""
        acct_str = f" ({acct})" if acct else ""
        lines.append(f"- **{d}** {desc} — {amt_str}{cat_str}{acct_str}")
    
    lines.append(f"\n**Total: ${abs(total):,.2f}**")
    
    return {
        "_display": "\n".join(lines),
        "transactions": [dict(r) for r in rows],
        "total": total,
    }


# =========================================================================
# spending-summary — category breakdown over a date range
# =========================================================================

async def spending_summary(month: Optional[str] = None) -> dict:
    """
    Monthly spending breakdown by category.
    month: YYYY-MM format. Defaults to current month.
    """
    if month:
        try:
            year, mo = month.split("-")
            start = date(int(year), int(mo), 1)
        except (ValueError, IndexError):
            start = date.today().replace(day=1)
    else:
        start = date.today().replace(day=1)
    
    # Last day of month
    if start.month == 12:
        end = date(start.year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(start.year, start.month + 1, 1) - timedelta(days=1)
    
    pool = get_pool()
    async with pool.acquire() as conn:
        # Category breakdown — allocation-aware via public.real_activity (counts
        # split children, excludes split parents + transfers + investments; R2.1/R2.2).
        cat_rows = await conn.fetch("""
            SELECT COALESCE(c.name, 'Uncategorized') as category,
                   SUM(ABS(ra.amount)) as total,
                   COUNT(*) as count
            FROM public.real_activity ra
            LEFT JOIN finance.categories c ON c.id = ra.category_id
            WHERE ra.posted_date >= $1 AND ra.posted_date <= $2
              AND ra.amount < 0
            GROUP BY c.name
            ORDER BY total DESC
        """, start, end)

        # Top 5 individual purchases (list of real spend rows; join txn for description)
        top_rows = await conn.fetch("""
            SELECT ra.posted_date, t.description, ra.amount, c.name as category
            FROM public.real_activity ra
            JOIN finance.transactions t ON t.id = ra.id
            LEFT JOIN finance.categories c ON c.id = ra.category_id
            WHERE ra.posted_date >= $1 AND ra.posted_date <= $2
              AND ra.amount < 0
            ORDER BY ra.amount ASC
            LIMIT 5
        """, start, end)

        # Total income
        income_row = await conn.fetchrow("""
            SELECT COALESCE(SUM(amount), 0) as total
            FROM public.real_activity
            WHERE posted_date >= $1 AND posted_date <= $2
              AND amount > 0
        """, start, end)
    
    total_spent = sum(float(r["total"]) for r in cat_rows)
    total_income = float(income_row["total"]) if income_row else 0
    
    lines = [f"**💵 Spending Summary — {start.strftime('%B %Y')}**\n"]
    lines.append(f"**Income:** ${total_income:,.2f}")
    lines.append(f"**Spending:** ${total_spent:,.2f}")
    lines.append(f"**Net:** ${(total_income - total_spent):,.2f}\n")
    
    if cat_rows:
        lines.append("**By Category:**")
        for r in cat_rows:
            cat = str(r["category"]).replace("_", " ")
            lines.append(f"- {cat}: **${float(r['total']):,.2f}** ({r['count']} transactions)")
    
    if top_rows:
        lines.append("\n**Top 5 Purchases:**")
        for r in top_rows:
            d = r["posted_date"].strftime("%m/%d") if r["posted_date"] else "—"
            desc = str(r["description"] or "—")[:50]
            amt = abs(float(r["amount"]))
            lines.append(f"- {d}: {desc} — **${amt:,.2f}**")
    
    return {
        "_display": "\n".join(lines),
        "month": start.strftime("%Y-%m"),
        "income": total_income,
        "spent": total_spent,
        "net": total_income - total_spent,
        "categories": [dict(r) for r in cat_rows],
        "top_purchases": [dict(r) for r in top_rows],
    }


# =========================================================================
# ask-db — NL→SQL via Anthropic Haiku, then execute against read-only role
# =========================================================================

# SQL safety is enforced by sql_guard.validate_select() (sqlglot parse) plus the
# de-escalated read-only execution in ask_db() — see below.

# Cache the schema info for 5 minutes (built once per request, schema rarely changes)
_SCHEMA_CACHE: Dict[str, Any] = {"text": None, "expires_at": 0}


async def _build_schema_prompt() -> str:
    """Build a schema-aware prompt by querying information_schema."""
    import time
    now = time.time()
    if _SCHEMA_CACHE["text"] and _SCHEMA_CACHE["expires_at"] > now:
        return _SCHEMA_CACHE["text"]
    
    pool = get_pool()
    async with pool.acquire() as conn:
        # Get all user schemas (skip system + bh_*)
        schemas = await conn.fetch("""
            SELECT DISTINCT table_schema
            FROM information_schema.tables
            WHERE table_schema NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
              AND table_schema NOT LIKE 'pg_%'
            ORDER BY table_schema
        """)
        
        sections = []
        for s in schemas:
            schema = s["table_schema"]
            # Skip public entirely: finance_reader (the role ask-db executes as)
            # has no access to public — it holds the bh_* auth/user tables. All
            # queryable domain data lives in finance/inventory/house/cook/files.
            if schema == "public":
                continue
            tables = await conn.fetch("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = $1 AND table_type = 'BASE TABLE'
                ORDER BY table_name
            """, schema)
            
            for t in tables:
                table = t["table_name"]
                cols = await conn.fetch("""
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema = $1 AND table_name = $2
                    ORDER BY ordinal_position
                """, schema, table)
                col_list = ", ".join(f"{c['column_name']} ({c['data_type']})" for c in cols)
                sections.append(f"{schema}.{table}: {col_list}")
        
        # Get distinct categories for finance queries
        try:
            cats = await conn.fetch("""
                SELECT DISTINCT name FROM finance.categories
                WHERE parent_id IS NOT NULL OR id NOT IN (SELECT DISTINCT parent_id FROM finance.categories WHERE parent_id IS NOT NULL)
                ORDER BY name
            """)
            cat_list = ", ".join(c["name"] for c in cats)
        except Exception:
            cat_list = ""
    
    schema_text = "\n".join(sections)
    
    prompt = f"""You are a SQL expert generating PostgreSQL queries.

AVAILABLE TABLES AND COLUMNS:
{schema_text}

CRITICAL COLUMN NAMES:
- finance.category_examples has a column named `description_pattern`. It does NOT have a column named `pattern`.
- public.bh_patterns has a column named `rule`. It does NOT have a column named `pattern`.

LEAF CATEGORIES (use these exact names): {cat_list}

CATEGORY MAPPING (natural language → leaf category):
- groceries → Food_Groceries
- dining/restaurants → Food_Dining
- gas/fuel → Trans_Gas
- car maintenance → Trans_Car_Maintenance
- car insurance → Trans_Car_Insurance
- mortgage → House_Mortgage
- utilities → House_Utilities
- house maintenance → House_Maintenance
- home improvement → House_Improvement
- furniture → House_Furniture

RULES:
1. Generate ONLY a single SELECT query. No INSERT, UPDATE, DELETE, DROP, etc.
2. Use schema-qualified table names: finance.transactions, inventory.tools, etc.
3. Prefer aggregation (GROUP BY, SUM, COUNT) over raw row dumps.
4. Always exclude transfers from spending: WHERE is_transfer = false
5. For "spending" use ABS(amount) and filter amount < 0.
6. For "income" filter amount > 0.
7. Add LIMIT 100 unless the question asks for a count/sum/total.
8. Return ONLY the SQL — no markdown fences, no explanation.
9. For "uncategorized" or "none" category requests, use `WHERE category_id IS NULL`.

Today is {date.today().isoformat()}.
"""
    
    _SCHEMA_CACHE["text"] = prompt
    _SCHEMA_CACHE["expires_at"] = now + 300  # 5 min cache
    return prompt


# Max rows ask-db will fetch/return. Enforced server-side via a cursor so a
# huge result set is never materialized in full (see the execution block).
_ASK_DB_MAX_ROWS = 100


async def ask_db(question: str) -> dict:
    """
    Natural-language question → Haiku-generated SQL → executed against Postgres.
    Returns the SQL, row count, and results.
    """
    if not question or not question.strip():
        return {"error": "No question provided", "_display": "⚠️ Please provide a question."}
    
    import os
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "Anthropic API key not configured"}
    
    schema_prompt = await _build_schema_prompt()
    
    # Call Haiku to generate SQL
    try:
        client = get_http_client()
        resp = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": resolve_role("fast"),
                "max_tokens": 1024,
                "system": schema_prompt,
                "messages": [{"role": "user", "content": question}],
            },
        )
        resp.raise_for_status()
        api_data = resp.json()
    except httpx.HTTPStatusError as e:
        return {"error": f"Anthropic API error: {e.response.status_code} {e.response.text[:200]}"}
    except Exception as e:
        return {"error": f"Failed to call Anthropic: {e}"}
    
    # Extract SQL from response
    content = api_data.get("content", [])
    sql = ""
    for block in content:
        if block.get("type") == "text":
            sql = block.get("text", "").strip()
            break
    
    # Strip markdown fences if Haiku added them despite instructions
    sql = re.sub(r'^```\w*\s*', '', sql)
    sql = re.sub(r'\s*```$', '', sql)
    sql = sql.strip().rstrip(";").strip()
    
    if not sql:
        return {"error": "Haiku returned empty SQL"}

    # Safety layer 1: parse and require a single read-only SELECT (sqlglot).
    ok, reason = validate_select(sql)
    if not ok:
        return {
            "error": f"Refused to execute generated SQL: {reason}",
            "sql_generated": sql,
            "_display": f"⚠️ Refused to execute generated SQL ({reason}).\n\n```sql\n{sql}\n```",
        }

    # Safety layer 2: execute with least privilege — drop to the read-only
    # finance_reader role (no access to bh_* / auth tables, not superuser) in a
    # READ ONLY transaction with timeouts. Even a malicious SELECT can't read
    # credentials, write, run server programs, run unbounded, or block on a lock.
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("SET TRANSACTION READ ONLY")
                await conn.execute("SET LOCAL statement_timeout = '5000ms'")
                # Cap time spent blocked on a lock (statement_timeout bounds
                # total wall-clock, but a fast-failing lock_timeout is clearer).
                await conn.execute("SET LOCAL lock_timeout = '2000ms'")
                # pg_catalog first so built-ins can't be shadowed; only the
                # finance_reader-readable schemas (migration 0002) — never
                # public (which holds bh_* / auth).
                await conn.execute(
                    "SET LOCAL search_path = pg_catalog, finance, inventory, house, cook, files"
                )
                await conn.execute("SET LOCAL ROLE finance_reader")
                # Server-side cursor: fetch only up to the cap instead of
                # materializing the entire result set. statement_timeout bounds
                # time, not memory — an unqualified SELECT * over a huge table
                # would otherwise be pulled in full before the display slice.
                # Fetch one extra row to detect (and signal) truncation.
                cur = await conn.cursor(sql)
                fetched = await cur.fetch(_ASK_DB_MAX_ROWS + 1)
        truncated = len(fetched) > _ASK_DB_MAX_ROWS
        rows = fetched[:_ASK_DB_MAX_ROWS]
    except Exception as e:
        return {
            "error": f"SQL execution failed: {e}",
            "sql_generated": sql,
            "_display": f"⚠️ SQL execution failed: {e}\n\n```sql\n{sql}\n```",
        }
    
    # Format results
    if not rows:
        return {
            "sql_generated": sql,
            "row_count": 0,
            "results": [],
            "_display": f"No results.\n\n```sql\n{sql}\n```",
        }
    
    # Convert rows to dicts (handle Decimal, date, etc.)
    results = []
    for r in rows:  # already capped server-side to _ASK_DB_MAX_ROWS
        d = {}
        for k, v in r.items():
            if isinstance(v, Decimal):
                d[k] = float(v)
            elif isinstance(v, (date,)):
                d[k] = v.isoformat()
            else:
                d[k] = v
        results.append(d)
    
    # Render display
    if len(results) == 1 and len(results[0]) == 1:
        # Single value (typical of COUNT/SUM)
        key, val = next(iter(results[0].items()))
        label = key.replace("_", " ")
        if isinstance(val, float):
            val_str = f"${val:,.2f}" if "amount" in key.lower() or "total" in key.lower() or "spent" in key.lower() or "balance" in key.lower() else f"{val:,.2f}"
        else:
            val_str = str(val)
        display = f"**{label}: {val_str}**"
    elif len(results) <= 50 and results and len(results[0]) >= 2:
        # Render as markdown table
        headers = list(results[0].keys())
        header_labels = [h.replace("_", " ").title() for h in headers]
        lines = [f"**📊 Results** ({len(rows)} rows)\n"]
        lines.append("| " + " | ".join(header_labels) + " |")
        lines.append("| " + " | ".join("---" for _ in headers) + " |")
        for row in results:
            vals = []
            for h in headers:
                v = row.get(h)
                if v is None:
                    vals.append("—")
                elif isinstance(v, float):
                    if "amount" in h.lower() or "total" in h.lower() or "balance" in h.lower() or "spent" in h.lower() or "price" in h.lower():
                        vals.append(f"${v:,.2f}" if v >= 0 else f"-${abs(v):,.2f}")
                    else:
                        vals.append(f"{v:,.2f}")
                else:
                    vals.append(str(v)[:60])
            lines.append("| " + " | ".join(vals) + " |")
        display = "\n".join(lines)
    else:
        # Big result — just dump JSON-ish
        lines = [f"**📊 Results** ({len(rows)} rows)\n"]
        for r in results[:30]:
            lines.append(f"- {json.dumps(r, default=str)}")
        if len(results) > 30:
            lines.append(f"\n*...and {len(results) - 30} more*")
        display = "\n".join(lines)

    if truncated:
        display += f"\n\n*Showing first {_ASK_DB_MAX_ROWS} rows; more exist — narrow the query for the rest.*"

    return {
        "sql_generated": sql,
        "row_count": len(rows),
        "truncated": truncated,
        "results": results,
        "_display": display,
    }


# =========================================================================
# list-files — list files in /files/* directories
# =========================================================================

async def list_files(path: str = "inbox") -> dict:
    """List files in a directory under /files/."""
    from pathlib import Path
    
    # Sanitize
    path = (path or "inbox").replace("..", "").strip("/")
    files_root = Path("/files")
    target = files_root / path
    
    if not target.exists() or not target.is_dir():
        return {"_display": f"Directory not found: `{path}`", "files": []}
    
    try:
        entries = sorted(target.iterdir())
    except PermissionError:
        return {"_display": f"Cannot access: `{path}`", "files": []}
    
    if not entries:
        return {"_display": f"📁 `{path}/` is empty", "files": []}
    
    files = [e for e in entries if e.is_file()]
    dirs = [e for e in entries if e.is_dir()]
    
    lines = [f"**📁 {path}/** ({len(entries)} items)\n"]
    
    for d in dirs[:20]:
        lines.append(f"- 📁 `{d.name}/`")
    
    for f in files[:30]:
        size = f.stat().st_size
        if size < 1024:
            sz = f"{size:,}B"
        elif size < 1024 * 1024:
            sz = f"{size/1024:.1f}KB"
        else:
            sz = f"{size/1024/1024:.1f}MB"
        icon = "🖼" if f.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp', '.gif') else "📄"
        lines.append(f"- {icon} `{f.name}` ({sz})")
    
    if len(entries) > 50:
        lines.append(f"\n*...and {len(entries) - 50} more*")
    
    return {
        "_display": "\n".join(lines),
        "path": path,
        "files": [{"name": f.name, "size": f.stat().st_size} for f in files],
        "dirs": [d.name for d in dirs],
    }
