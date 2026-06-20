"""One-time idempotent historical transfer-flag backfill (R6, critic M3-b).

Existing history has no `is_transfer` set (this spec introduces the first writer
of the column). This pass flags past transfers/debt-payments that the detector is
*confident* about (>= τ_transfer) — counterpart-matched legs and confirmed
liability payments. Ambiguous single-leg cases are deliberately left unflagged
(they surface as "transfer?" review items once the live cascade runs), so the
backfill never silently zeros a spending total.

Runs in its own connection, NOT inside the nightly critical section. Idempotent:
already-flagged rows and `is_transfer_manual` rows are skipped, so re-running is a
true no-op for converged rows.
"""

from __future__ import annotations

import logging

from ...database import get_pool
from .config import load_config
from .base import TxnContext
from .transfer import TransferDetector

logger = logging.getLogger(__name__)


async def backfill_transfer_flags(*, limit: int | None = None) -> dict:
    """Flag high-confidence historical transfers. Respects is_transfer_manual.

    Returns {"scanned": n, "flagged": m}. Per-row commit so a partial run is
    durable and resumable (R5.2)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        cfg = await load_config(conn)
        tau = cfg.threshold("transfer")
        detector = TransferDetector(conn)

        query = (
            "SELECT id, account_id, posted_date, amount, description, memo, "
            "       is_transfer_manual, "
            "       (SELECT account_type FROM finance.accounts a WHERE a.id = t.account_id) AS account_type "
            "FROM finance.transactions t "
            "WHERE is_transfer = false AND is_transfer_manual = false "
            "ORDER BY posted_date DESC"
        )
        if limit:
            query += f" LIMIT {int(limit)}"
        rows = await conn.fetch(query)

        flagged = 0
        for r in rows:
            ctx = TxnContext(
                txn_id=r["id"], description=r["description"] or "",
                amount=float(r["amount"]), account_id=r["account_id"],
                account_type=r["account_type"], posted_date=r["posted_date"],
                memo=r["memo"], is_transfer_manual=r["is_transfer_manual"],
            )
            decision = await detector.classify(ctx)
            if decision.is_transfer and decision.confidence >= tau:
                # Guarded write: never overrides a manual value, never re-flags.
                result = await conn.execute(
                    "UPDATE finance.transactions SET is_transfer = true, updated_at = now() "
                    "WHERE id = $1 AND is_transfer = false AND is_transfer_manual = false",
                    r["id"],
                )
                if result.endswith(" 1"):
                    flagged += 1

    logger.info("Transfer-flag backfill: flagged %d/%d (τ_transfer=%.2f)", flagged, len(rows), tau)
    return {"scanned": len(rows), "flagged": flagged}
