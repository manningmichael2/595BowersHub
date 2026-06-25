"""Insight store — upsert, dedupe, cooldown, dismissal lifecycle (R2.4, R2.7).

The store is the only writer of finance.insights. Upsert dedupes on
(insight_type, merchant_key, period): a nightly re-run refreshes an *active*
insight's figures but NEVER resurrects a dismissed/actioned one (a dismissal
permanently resolves that (type, merchant, period); a new month is a new period,
so it legitimately re-raises). Surfaced insights are ranked by dollar impact.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .config import InsightConfig
from .detectors import Candidate


async def upsert_candidates(
    conn, candidates: List[Candidate], cfg: InsightConfig
) -> List[int]:
    """Upsert each candidate; return the ids of the rows that were *newly raised*
    this run (for notification). Existing active rows are refreshed in place;
    dismissed/actioned rows are left untouched (not resurrected)."""
    cooldown_days = int(cfg.get("insights_cooldown_days", 7))
    new_ids: List[int] = []
    for c in candidates:
        row = await conn.fetchrow(
            """
            INSERT INTO finance.insights
                (insight_type, merchant_key, period, dollar_impact, figures, reason,
                 cooldown_until, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, now() + ($7 * interval '1 day'), now())
            ON CONFLICT (insight_type, merchant_key, period) DO UPDATE
                SET dollar_impact = EXCLUDED.dollar_impact,
                    figures       = EXCLUDED.figures,
                    reason        = EXCLUDED.reason,
                    updated_at    = now()
                WHERE finance.insights.status = 'active'
            RETURNING id, (xmax = 0) AS inserted
            """,
            c.insight_type, c.merchant_key, c.period,
            c.dollar_impact, c.figures, c.reason, cooldown_days,
        )
        if row is not None and row["inserted"]:
            new_ids.append(row["id"])
    return new_ids


async def list_insights(conn, status: Optional[str] = "active") -> List[Dict[str, Any]]:
    """List insights (optionally filtered by status), ranked by dollar impact
    (R2.4) then most-recent."""
    if status is None:
        rows = await conn.fetch(
            "SELECT * FROM finance.insights ORDER BY dollar_impact DESC, created_at DESC"
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM finance.insights WHERE status = $1 "
            "ORDER BY dollar_impact DESC, created_at DESC",
            status,
        )
    return [dict(r) for r in rows]


async def dismiss(conn, insight_id: int) -> bool:
    """Permanently resolve an insight for its (type, merchant, period)."""
    result = await conn.execute(
        "UPDATE finance.insights SET status = 'dismissed', dismissed_at = now(), "
        "updated_at = now() WHERE id = $1",
        insight_id,
    )
    return result.endswith("1")


async def dismiss_all_active(conn) -> int:
    """Dismiss every currently-active insight in one statement; return the count
    dismissed (lets the user clear the queue without acting on each one)."""
    result = await conn.execute(
        "UPDATE finance.insights SET status = 'dismissed', dismissed_at = now(), "
        "updated_at = now() WHERE status = 'active'"
    )
    # asyncpg returns e.g. "UPDATE 7" — the trailing token is the row count.
    return int(result.rsplit(" ", 1)[-1]) if result else 0


async def reopen(conn, insight_id: int) -> bool:
    """Un-dismiss: make a previously dismissed/actioned insight active again."""
    result = await conn.execute(
        "UPDATE finance.insights SET status = 'active', dismissed_at = NULL, "
        "actioned_at = NULL, updated_at = now() WHERE id = $1",
        insight_id,
    )
    return result.endswith("1")


async def mark_actioned(conn, insight_id: int) -> bool:
    """Mark that the user acted on the insight (e.g. created a rule)."""
    result = await conn.execute(
        "UPDATE finance.insights SET status = 'actioned', actioned_at = now(), "
        "updated_at = now() WHERE id = $1",
        insight_id,
    )
    return result.endswith("1")
