"""Idempotent transfer-link backfill (R1.6) — links the two legs of historical
transfers via TransferLinker. Runs in its own pool connection (not the categorizer
critical section); per-pair commit makes it resumable, and the `transfer_id IS NULL`
+ `transfer_link_manual = false` guards make a re-run a true no-op for converged
rows. Also the nightly link step (R1.9), run after the categorizer flags transfers.
"""

from __future__ import annotations

import logging

from ...database import get_pool
from .config import load_config
from .transfers import TransferLinker

logger = logging.getLogger(__name__)


async def backfill_transfer_links() -> dict:
    pool = get_pool()
    async with pool.acquire() as conn:
        cfg = await load_config(conn)
        linker = TransferLinker(
            conn,
            amount_tolerance=cfg.match_amount_tolerance,
            date_window_days=cfg.match_date_window_days,
        )
        result = await linker.link_pass()
    logger.info("transfer-link backfill: %s", result)
    return result
