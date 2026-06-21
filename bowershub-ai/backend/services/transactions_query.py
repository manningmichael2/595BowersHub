"""Transactions explorer query (finance dashboard — Monarch/Origin-style).

A flexible, parameterized search over finance.transactions: text + category +
month + account + status filters, sortable, paginated, with allocation-aware
by-category subtotals and in/out totals computed from public.real_activity (split
children counted, transfers + investments excluded — the canonical spend/income
rule). The LIST shows top-level rows (parent_id IS NULL); split parents appear
once and their children roll up into the subtotals via real_activity.
"""

from __future__ import annotations

_SORTS = {
    "date": "t.posted_date",
    "amount": "t.amount",
    "category": "c.name",
    "description": "t.description",
}


def _list_filters(f: dict) -> tuple[list[str], list]:
    """WHERE fragments + params for the transaction LIST (on finance.transactions t)."""
    where = ["t.parent_id IS NULL"]   # top-level rows only (children nest under parents)
    params: list = []

    def p(val):
        params.append(val)
        return f"${len(params)}"

    if f.get("q"):
        ph = p(f"%{f['q']}%")
        where.append(f"(t.description ILIKE {ph} OR t.merchant_key ILIKE {ph})")
    if f.get("category_id") is not None:
        where.append(f"t.category_id = {p(f['category_id'])}")
    if f.get("month"):
        where.append(f"date_trunc('month', t.posted_date) = {p(f['month'])}")
    if f.get("account_id"):
        where.append(f"t.account_id = {p(f['account_id'])}")

    status = f.get("status") or "all"
    if status == "uncategorized":
        where.append("t.category_id IS NULL AND t.is_transfer = false AND t.is_split = false")
    elif status == "spending":
        where.append("t.amount < 0 AND t.is_transfer = false")
    elif status == "income":
        where.append("t.amount > 0 AND t.is_transfer = false")
    elif status == "transfers":
        where.append("t.is_transfer = true")
    return where, params


async def search_transactions(conn, *, q=None, category_id=None, month=None,
                              account_id=None, status="all", sort="date",
                              order="desc", limit=100, offset=0) -> dict:
    f = {"q": q, "category_id": category_id, "month": month,
         "account_id": account_id, "status": status}
    where, params = _list_filters(f)
    where_sql = " AND ".join(where)
    sort_col = _SORTS.get(sort, "t.posted_date")
    order_sql = "ASC" if str(order).lower() == "asc" else "DESC"
    limit = max(1, min(int(limit), 500))

    rows = await conn.fetch(
        f"""
        SELECT t.id, t.posted_date::text AS posted_date, t.description, t.merchant_key,
               t.amount, t.account_id, a.account_name, t.category_id, c.name AS category_name,
               t.is_transfer, t.is_split, t.cleared
        FROM finance.transactions t
        LEFT JOIN finance.categories c ON c.id = t.category_id
        LEFT JOIN finance.accounts a ON a.id = t.account_id
        WHERE {where_sql}
        ORDER BY {sort_col} {order_sql} NULLS LAST, t.id
        LIMIT {limit} OFFSET {max(0, int(offset))}
        """,
        *params,
    )
    total_count = await conn.fetchval(
        f"SELECT count(*) FROM finance.transactions t WHERE {where_sql}", *params)

    subtotals, totals = await _aggregates(conn, f)

    return {
        "items": [dict(r) | {"amount": float(r["amount"])} for r in rows],
        "count": total_count,
        "subtotals": subtotals,
        "totals": totals,
    }


async def _aggregates(conn, f: dict) -> tuple[list[dict], dict]:
    """Allocation-aware by-category subtotals + in/out totals from real_activity
    (spend/income only — excludes transfers/investments/split parents)."""
    where = ["1=1"]
    params: list = []

    def p(val):
        params.append(val)
        return f"${len(params)}"

    if f.get("q"):
        ph = p(f"%{f['q']}%")
        where.append(f"(t.description ILIKE {ph} OR t.merchant_key ILIKE {ph})")
    if f.get("category_id") is not None:
        where.append(f"ra.category_id = {p(f['category_id'])}")
    if f.get("month"):
        where.append(f"date_trunc('month', ra.posted_date) = {p(f['month'])}")
    if f.get("account_id"):
        where.append(f"ra.account_id = {p(f['account_id'])}")
    if f.get("status") == "income":
        where.append("ra.amount > 0")
    elif f.get("status") in ("spending", "uncategorized"):
        where.append("ra.amount < 0")
    where_sql = " AND ".join(where)

    sub_rows = await conn.fetch(
        f"""
        SELECT COALESCE(c.name, 'Uncategorized') AS category,
               SUM(ra.amount) AS total, count(*) AS n
        FROM public.real_activity ra
        JOIN finance.transactions t ON t.id = ra.id
        LEFT JOIN finance.categories c ON c.id = ra.category_id
        WHERE {where_sql}
        GROUP BY c.name
        ORDER BY SUM(ABS(ra.amount)) DESC
        """,
        *params,
    )
    tot = await conn.fetchrow(
        f"""
        SELECT COALESCE(SUM(ra.amount) FILTER (WHERE ra.amount > 0), 0) AS income,
               COALESCE(SUM(ABS(ra.amount)) FILTER (WHERE ra.amount < 0), 0) AS spending
        FROM public.real_activity ra
        JOIN finance.transactions t ON t.id = ra.id
        WHERE {where_sql}
        """,
        *params,
    )
    subtotals = [{"category": r["category"], "total": float(r["total"]), "count": r["n"]} for r in sub_rows]
    totals = {"income": float(tot["income"]), "spending": float(tot["spending"])}
    return subtotals, totals
