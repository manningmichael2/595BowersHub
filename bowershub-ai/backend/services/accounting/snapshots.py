"""Balance-snapshot history (R3.5) — one row per account per day in
finance.balance_snapshots, the data source for net-worth-over-time (R3.6).

Called from the SimpleFin sync after balances update; keyed on the account's
last_balance_date (NULL → today), so same-day re-syncs are last-write-wins via the
PK. History begins when snapshotting turns on — past balances can't be
reconstructed (no historical source), which is expected/standard.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def snapshot_all_accounts(conn) -> dict:
    """Upsert a balance snapshot for every account with a known balance. Runs in
    the caller's connection (the sync transaction). Idempotent per (account, date)."""
    result = await conn.execute(
        """
        INSERT INTO finance.balance_snapshots (account_id, snapshot_date, balance)
        SELECT id, COALESCE(last_balance_date, CURRENT_DATE), last_balance
        FROM finance.accounts
        WHERE last_balance IS NOT NULL
        ON CONFLICT (account_id, snapshot_date)
        DO UPDATE SET balance = EXCLUDED.balance
        """
    )
    # asyncpg returns e.g. "INSERT 0 16"; the trailing number is rows affected.
    n = int(result.split()[-1]) if result and result.split()[-1].isdigit() else 0
    logger.info("balance snapshots upserted: %d", n)
    return {"snapshotted": n}
