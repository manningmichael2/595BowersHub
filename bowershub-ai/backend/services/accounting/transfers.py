"""TransferLinker — persist the two-leg link of a matched transfer (R1.1-1.9).

The categorization cascade's TransferDetector already *flags* `is_transfer`; this
links the two legs durably via the `transfer_id` self-FK so a transfer is one
logical movement. It reuses the same counterpart heuristic (opposite sign,
near-equal magnitude, different account, date window) restricted to rows that are
*already* transfers and unlinked.

Ownership (R1.9): the auto path writes ONLY `transfer_id` — never `is_transfer`
(the nightly detector stays the sole nightly `is_transfer` writer). The manual
`link()` path is the one exception (a user action) and marks `transfer_link_manual`
sticky, mirroring `is_transfer_manual`. Asymmetric gate (R1.3): a leg with more
than one candidate counterpart is left for the review queue, never auto-linked.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class TransferLinker:
    def __init__(self, conn, *, amount_tolerance: float = 0.01, date_window_days: int = 4):
        self._conn = conn
        self._amount_tolerance = amount_tolerance
        self._date_window_days = date_window_days

    async def _candidates(self, leg: dict) -> list[dict]:
        """Unlinked transfer legs in a different account that could pair with `leg`
        (opposite sign, near-equal magnitude, within the date window)."""
        rows = await self._conn.fetch(
            """
            SELECT id, account_id, amount, posted_date
            FROM finance.transactions
            WHERE account_id <> $1
              AND id <> $2
              AND is_transfer = true
              AND transfer_id IS NULL
              AND transfer_link_manual = false
              AND sign(amount) = -sign($3::numeric)
              AND abs(abs(amount) - abs($3::numeric)) <= $4
              AND abs(posted_date - $5::date) <= $6
            ORDER BY abs(posted_date - $5::date)
            """,
            leg["account_id"], leg["id"], leg["amount"],
            self._amount_tolerance, leg["posted_date"], self._date_window_days,
        )
        return [dict(r) for r in rows]

    async def _set_link(self, a_id: str, b_id: str) -> bool:
        """Symmetrically link a<->b, guarded so a concurrently-linked leg is not
        clobbered. Returns True only if BOTH sides were still unlinked (R1.8)."""
        async with self._conn.transaction():
            r1 = await self._conn.execute(
                "UPDATE finance.transactions SET transfer_id=$2, updated_at=now() "
                "WHERE id=$1 AND transfer_id IS NULL", a_id, b_id)
            r2 = await self._conn.execute(
                "UPDATE finance.transactions SET transfer_id=$2, updated_at=now() "
                "WHERE id=$1 AND transfer_id IS NULL", b_id, a_id)
            if not (r1.endswith(" 1") and r2.endswith(" 1")):
                raise _Rollback()  # one side already linked → undo both
        return True

    async def link_pass(self) -> dict:
        """Auto-link unique counterparts over all unlinked transfer legs (R1.2,
        R1.3). Per-pair commit; ambiguous (>1 candidate) legs are skipped."""
        legs = await self._conn.fetch(
            "SELECT id, account_id, amount, posted_date FROM finance.transactions "
            "WHERE is_transfer = true AND transfer_id IS NULL AND transfer_link_manual = false "
            "ORDER BY posted_date")
        linked = ambiguous = 0
        for leg in legs:
            leg = dict(leg)
            # Re-check: a prior pair this pass may have linked it.
            still = await self._conn.fetchval(
                "SELECT transfer_id IS NULL FROM finance.transactions WHERE id=$1", leg["id"])
            if not still:
                continue
            cands = await self._candidates(leg)
            if len(cands) != 1:
                if len(cands) > 1:
                    ambiguous += 1
                continue
            # Reciprocal uniqueness (R1.3): only auto-link when the match is unique
            # in BOTH directions. Ambiguity is directional — A may see one candidate
            # B while B sees several — so a one-sided unique match must not be linked.
            rev = await self._candidates(cands[0])
            if len(rev) != 1 or rev[0]["id"] != leg["id"]:
                ambiguous += 1
                continue
            try:
                if await self._set_link(leg["id"], cands[0]["id"]):
                    linked += 1
            except _Rollback:
                continue
        result = {"scanned": len(legs), "linked": linked, "ambiguous": ambiguous}
        logger.info("transfer link pass: %s", result)
        return result

    async def link(self, a_id: str, b_id: str) -> dict:
        """Manual link (R1.5): mark both legs transfers + linked + sticky. This is
        the only path that sets is_transfer (a user action)."""
        if a_id == b_id:
            raise ValueError("cannot link a transaction to itself")
        async with self._conn.transaction():
            res = await self._conn.execute(
                "UPDATE finance.transactions "
                "SET transfer_id=$2, is_transfer=true, transfer_link_manual=true, updated_at=now() "
                "WHERE id=$1", a_id, b_id)
            if not res.endswith(" 1"):
                raise ValueError(f"transaction {a_id} not found")
            res = await self._conn.execute(
                "UPDATE finance.transactions "
                "SET transfer_id=$2, is_transfer=true, transfer_link_manual=true, updated_at=now() "
                "WHERE id=$1", b_id, a_id)
            if not res.endswith(" 1"):
                raise ValueError(f"transaction {b_id} not found")
        return {"linked": [a_id, b_id]}

    async def unlink(self, txn_id: str) -> dict:
        """Clear both sides of a link (R1.5). Leaves is_transfer as-is."""
        async with self._conn.transaction():
            other = await self._conn.fetchval(
                "SELECT transfer_id FROM finance.transactions WHERE id=$1", txn_id)
            await self._conn.execute(
                "UPDATE finance.transactions SET transfer_id=NULL, transfer_link_manual=false, updated_at=now() "
                "WHERE id=$1 OR id=$2", txn_id, other)
        return {"unlinked": [txn_id, other] if other else [txn_id]}


class _Rollback(Exception):
    """Internal: abort a link transaction when a leg was already linked."""
