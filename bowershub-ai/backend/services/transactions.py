"""
Native transactions skill — replaces the n8n webhook for /transactions command.

Behavior:
- /transactions (no args): show last 15 transactions as a markdown table
- /transactions last week: show transactions from the past 7 days
- /transactions <search>: filter by description

Returns a dict with '_display' key containing pre-formatted markdown.
"""
import logging
from datetime import date, timedelta
from typing import Optional

from backend.database import get_pool

logger = logging.getLogger(__name__)

# Simple date range parsing for common phrases
DATE_PHRASES = {
    "today": lambda: (date.today(), date.today()),
    "yesterday": lambda: (date.today() - timedelta(days=1), date.today() - timedelta(days=1)),
    "last week": lambda: (date.today() - timedelta(days=7), date.today()),
    "this week": lambda: (date.today() - timedelta(days=date.today().weekday()), date.today()),
    "last month": lambda: (
        (date.today().replace(day=1) - timedelta(days=1)).replace(day=1),
        date.today().replace(day=1) - timedelta(days=1),
    ),
    "this month": lambda: (date.today().replace(day=1), date.today()),
    "last 30 days": lambda: (date.today() - timedelta(days=30), date.today()),
    "last 7 days": lambda: (date.today() - timedelta(days=7), date.today()),
    "last 14 days": lambda: (date.today() - timedelta(days=14), date.today()),
}


def _parse_date_range(args: str):
    """Try to parse a date range from user input. Returns (start, end) or None."""
    args_lower = args.strip().lower()
    
    # Check common phrases
    if args_lower in DATE_PHRASES:
        return DATE_PHRASES[args_lower]()
    
    # Try YYYY-MM-DD format (single date or range)
    parts = args.split()
    if len(parts) == 1:
        try:
            d = date.fromisoformat(parts[0])
            return (d, d)
        except ValueError:
            pass
    
    # Try "YYYY-MM-DD to YYYY-MM-DD" or "YYYY-MM-DD YYYY-MM-DD"
    if len(parts) >= 2:
        clean = [p for p in parts if p.lower() not in ("to", "-", "through")]
        if len(clean) == 2:
            try:
                return (date.fromisoformat(clean[0]), date.fromisoformat(clean[1]))
            except ValueError:
                pass
    
    return None


async def get_transactions(args: Optional[str] = None) -> dict:
    """
    Main entry point for the /transactions slash command.
    
    - No args: show last 15 transactions
    - Date phrase: filter by date range
    - Text: search by description
    """
    pool = get_pool()
    args = (args or "").strip()

    if not args:
        return await _recent_transactions(pool, limit=15)

    # Try date range first
    date_range = _parse_date_range(args)
    if date_range:
        return await _transactions_by_date(pool, date_range[0], date_range[1])

    # Otherwise treat as a search term
    return await _search_transactions(pool, args)


async def _recent_transactions(pool, limit: int = 15) -> dict:
    """Show the most recent transactions."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.posted_date, t.description, t.amount, c.name as category
            FROM finance.transactions t
            LEFT JOIN finance.categories c ON c.id = t.category_id
            WHERE t.is_transfer = false
            ORDER BY t.posted_date DESC, t.id DESC
            LIMIT $1
        """, limit)

    if not rows:
        return {"_display": "No transactions found."}

    return {"_display": _format_transaction_table(rows, f"Last {limit} transactions")}


async def _transactions_by_date(pool, start: date, end: date) -> dict:
    """Show transactions in a date range."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.posted_date, t.description, t.amount, c.name as category
            FROM finance.transactions t
            LEFT JOIN finance.categories c ON c.id = t.category_id
            WHERE t.posted_date >= $1 AND t.posted_date <= $2
            AND t.is_transfer = false
            ORDER BY t.posted_date DESC, t.id DESC
            LIMIT 50
        """, start, end)

    if not rows:
        return {"_display": f"No transactions found between {start} and {end}."}

    # Calculate total
    total = sum(float(r["amount"]) for r in rows)
    title = f"Transactions: {start} → {end}"
    footer = f"\n**Total: ${abs(total):,.2f}** ({len(rows)} transactions)"
    if len(rows) == 50:
        footer += "\n*Showing first 50 results*"

    return {"_display": _format_transaction_table(rows, title) + footer}


async def _search_transactions(pool, term: str) -> dict:
    """Search transactions by description OR category name."""
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.posted_date, t.description, t.amount, c.name as category
            FROM finance.transactions t
            LEFT JOIN finance.categories c ON c.id = t.category_id
            WHERE (t.description ILIKE $1 OR c.name ILIKE $1)
            AND t.is_transfer = false
            ORDER BY t.posted_date DESC
            LIMIT 30
        """, f"%{term}%")

    if not rows:
        return {"_display": f'No transactions matching "{term}".'}

    total = sum(float(r["amount"]) for r in rows)
    title = f'Transactions matching "{term}"'
    footer = f"\n**Total: ${abs(total):,.2f}** ({len(rows)} transactions)"

    return {"_display": _format_transaction_table(rows, title) + footer}


def _format_transaction_table(rows, title: str) -> str:
    """Format transaction rows as clean readable text (no pipe tables)."""
    lines = [f"**💳 {title}**", ""]

    total = 0.0
    for row in rows:
        d = row["posted_date"]
        date_str = d.strftime("%m/%d") if d else "—"
        desc = str(row["description"] or "—")[:45]
        amount = float(row["amount"])
        total += amount
        category = str(row["category"] or "").replace("_", " ")

        if amount >= 0:
            amount_str = f"+${amount:,.2f}"
        else:
            amount_str = f"-${abs(amount):,.2f}"

        cat_str = f" · {category}" if category and category != "—" else ""
        lines.append(f"- **{date_str}** {desc} — {amount_str}{cat_str}")

    lines.append("")
    if total >= 0:
        lines.append(f"**Total: +${total:,.2f}** ({len(rows)} transactions)")
    else:
        lines.append(f"**Total: -${abs(total):,.2f}** ({len(rows)} transactions)")

    return "\n".join(lines)


async def get_large_transactions(threshold: float = 100.0) -> dict:
    """Show transactions over a threshold amount (last 30 days)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.posted_date, t.description, t.amount, c.name as category
            FROM finance.transactions t
            LEFT JOIN finance.categories c ON c.id = t.category_id
            WHERE ABS(t.amount) >= $1
            AND t.is_transfer = false
            AND t.posted_date >= CURRENT_DATE - 30
            ORDER BY ABS(t.amount) DESC
            LIMIT 30
        """, threshold)

    if not rows:
        return {"_display": f"No transactions over ${threshold:.0f} in the last 30 days."}

    total = sum(abs(float(r["amount"])) for r in rows)
    title = f"Large transactions (>${threshold:.0f}, last 30 days)"
    footer = f"\n**Total: ${total:,.2f}** ({len(rows)} transactions)"
    return {"_display": _format_transaction_table(rows, title) + footer}


async def get_recurring_transactions() -> dict:
    """Show likely recurring charges (same description appearing 2+ months)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT 
                UPPER(SUBSTRING(description FROM '^[A-Za-z ]+')) as merchant,
                COUNT(DISTINCT DATE_TRUNC('month', posted_date)) as months_seen,
                ROUND(AVG(ABS(amount))::numeric, 2) as avg_amount,
                MAX(posted_date) as last_seen
            FROM finance.transactions
            WHERE amount < 0
            AND is_transfer = false
            AND posted_date >= CURRENT_DATE - interval '90 days'
            GROUP BY UPPER(SUBSTRING(description FROM '^[A-Za-z ]+'))
            HAVING COUNT(DISTINCT DATE_TRUNC('month', posted_date)) >= 2
            ORDER BY ROUND(AVG(ABS(amount))::numeric, 2) DESC
            LIMIT 20
        """)

    if not rows:
        return {"_display": "No recurring charges detected in the last 90 days."}

    lines = ["**🔄 Likely Recurring Charges** (last 90 days)\n"]
    total = 0.0
    for r in rows:
        merchant = (r["merchant"] or "Unknown").strip()[:30]
        avg = float(r["avg_amount"])
        total += avg
        months = r["months_seen"]
        lines.append(f"- **{merchant}** — ~${avg:,.2f}/mo ({months} months)")

    lines.append(f"\n**Estimated monthly recurring: ~${total:,.2f}**")
    return {"_display": "\n".join(lines)}


async def get_uncategorized_transactions() -> dict:
    """Show recent transactions that have no category assigned."""
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT t.posted_date, t.description, t.amount, NULL as category
            FROM finance.transactions t
            WHERE t.category_id IS NULL
            AND t.is_transfer = false
            ORDER BY t.posted_date DESC
            LIMIT 20
        """)

    if not rows:
        return {"_display": "✅ All recent transactions are categorized!"}

    title = f"Uncategorized transactions ({len(rows)})"
    return {"_display": _format_transaction_table(rows, title)}
