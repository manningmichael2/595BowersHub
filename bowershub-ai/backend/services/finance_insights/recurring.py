"""Recurring-charge detection at the service/query level (R2.3).

Extracted verbatim from the route-bound query in routers/finance_review.py so
both the `/recurring` endpoint and the nightly detectors share one detection
(don't reinvent it). Behaviour is unchanged for the route.
"""

from __future__ import annotations

_RECURRING_SQL = """
    WITH per_merchant AS (
        SELECT merchant_key,
               count(*) AS occurrences,
               avg(amount) AS avg_amount,
               stddev_pop(abs(amount)) AS amt_sd,
               avg(abs(amount)) AS avg_abs,
               max(posted_date)::text AS last_seen,
               (max(posted_date) - min(posted_date))::float
                   / NULLIF(count(*) - 1, 0) AS avg_interval_days
        FROM finance.transactions
        WHERE merchant_key IS NOT NULL AND is_transfer = false AND amount < 0
        GROUP BY merchant_key
    )
    SELECT merchant_key, occurrences, avg_amount, last_seen, avg_interval_days
    FROM per_merchant
    WHERE occurrences >= $1
      AND (avg_abs = 0 OR COALESCE(amt_sd, 0) / NULLIF(avg_abs, 0) <= $2)
    ORDER BY occurrences DESC, merchant_key
"""


async def recurring_charges(conn, *, min_occurrences: int, amount_tolerance_frac: float):
    """Return recurring-charge rows (merchant_key, occurrences, avg_amount,
    last_seen, avg_interval_days). ``amount_tolerance_frac`` is already a fraction
    (e.g. 0.15), not a percent."""
    return await conn.fetch(_RECURRING_SQL, int(min_occurrences), float(amount_tolerance_frac))
