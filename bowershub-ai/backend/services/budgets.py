"""Budgets (finance-budgets-splits R3.x) — per-category monthly targets.

Reuses the existing `finance.budgets` table (UNIQUE (category_id, month)) and the
live `alerts.check_budgets` loop. "Actual" is computed from the allocation-aware
`public.real_activity` view (split children counted, transfers + investments
excluded), so it agrees with every other rollup. Alert thresholds are DB-driven
(`finance.accounting_config`), not constants. `finance.budgets` is the single
budget store; `finance.categories.budget_monthly` is deprecated/unread (R3.1).
"""

from __future__ import annotations

_DEFAULT_WARN = 0.8
_DEFAULT_OVER = 1.0


async def alert_thresholds(conn) -> tuple[float, float]:
    """(warn_ratio, over_ratio) from accounting_config, with safe defaults (R3.5)."""
    rows = await conn.fetch(
        "SELECT key, value FROM finance.accounting_config "
        "WHERE key IN ('budget_warn_ratio', 'budget_over_ratio')")
    raw = {r["key"]: r["value"] for r in rows}
    return (float(raw.get("budget_warn_ratio", _DEFAULT_WARN)),
            float(raw.get("budget_over_ratio", _DEFAULT_OVER)))


async def list_budgets(conn, month) -> list[dict]:
    rows = await conn.fetch(
        "SELECT b.category_id, c.name AS category, b.limit_amount "
        "FROM finance.budgets b JOIN finance.categories c ON c.id = b.category_id "
        "WHERE b.month = $1 ORDER BY c.name", month)
    return [{"category_id": r["category_id"], "category": r["category"],
             "limit_amount": float(r["limit_amount"])} for r in rows]


async def upsert_budget(conn, category_id: int, month, limit_amount: float) -> dict:
    await conn.execute(
        "INSERT INTO finance.budgets (category_id, month, limit_amount) VALUES ($1, $2, $3) "
        "ON CONFLICT (category_id, month) DO UPDATE SET limit_amount = EXCLUDED.limit_amount",
        category_id, month, limit_amount)
    return {"category_id": category_id, "month": month.isoformat(), "limit_amount": limit_amount}


async def budget_vs_actual(conn, month) -> list[dict]:
    """Budgeted/spent/remaining per category for `month` (first-of-month date).
    Actual is allocation-aware via real_activity (R3.3)."""
    rows = await conn.fetch(
        """
        SELECT c.id AS category_id, c.name AS category,
               COALESCE(b.limit_amount, 0) AS budgeted,
               COALESCE(s.actual, 0) AS actual
        FROM finance.categories c
        LEFT JOIN finance.budgets b ON b.category_id = c.id AND b.month = $1
        LEFT JOIN (
            SELECT category_id, SUM(ABS(amount)) AS actual
            FROM public.real_activity
            WHERE amount < 0 AND date_trunc('month', posted_date) = $1
            GROUP BY category_id
        ) s ON s.category_id = c.id
        WHERE b.id IS NOT NULL OR s.actual IS NOT NULL
        ORDER BY c.name
        """, month)
    out = []
    for r in rows:
        budgeted, actual = float(r["budgeted"]), float(r["actual"])
        out.append({
            "category_id": r["category_id"], "category": r["category"],
            "budgeted": budgeted, "actual": actual,
            "remaining": round(budgeted - actual, 2) if budgeted else None,
        })
    return out
