"""Nightly insight runner (R2.1, R2.8).

Runs at 03:00 (after the 02:30 categorizer). Single-flight via a Postgres
advisory lock; gated on the categorizer's readiness watermark for today's window
and the global kill-switch; per-detector try/except so one detector's failure
can't sink the run. Every invocation writes a finance.insight_runs summary whose
status records WHY nothing happened (skipped-not-ready / skipped-disabled /
errored) so a silent no-op is never mistaken for "nothing detected".
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from backend.database import get_pool

from .config import load_insight_config
from .detectors import DETECTORS
from .store import upsert_candidates

logger = logging.getLogger(__name__)

# Distinct advisory-lock key for the insight runner (single-flight across workers).
_ADVISORY_LOCK_KEY = 0x46494E53  # "FINS"
_CATEGORIZER_JOB = "categorizer"


async def _record_run(conn, *, status: str, detected: int = 0,
                      suppressed: Optional[Dict[str, Any]] = None,
                      error: Optional[str] = None) -> None:
    await conn.execute(
        "INSERT INTO finance.insight_runs (finished_at, status, detected, suppressed, error) "
        "VALUES (now(), $1, $2, $3, $4)",
        status, detected, suppressed or {}, error,
    )


async def run_insight_agent(pool=None) -> dict:
    """Entry point for the scheduler. Returns a small status dict (also for tests)."""
    pool = pool or get_pool()
    async with pool.acquire() as lock_conn:
        got = await lock_conn.fetchval("SELECT pg_try_advisory_lock($1)", _ADVISORY_LOCK_KEY)
        if not got:
            logger.info("insight runner: another run holds the lock; skipping")
            return {"status": "skipped-locked"}
        try:
            return await _run(pool)
        finally:
            await lock_conn.fetchval("SELECT pg_advisory_unlock($1)", _ADVISORY_LOCK_KEY)


async def _run(pool) -> dict:
    async with pool.acquire() as conn:
        cfg = await load_insight_config(conn)

        # Global kill-switch (R2) — recorded, never silent.
        if not cfg.insights_enabled:
            await _record_run(conn, status="skipped-disabled")
            return {"status": "skipped-disabled"}

        # Readiness gate (R2.1): the categorizer must have completed today's window.
        ready = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM finance.job_runs "
            "WHERE job_name = $1 AND status = 'completed' AND ran_for = CURRENT_DATE)",
            _CATEGORIZER_JOB,
        )
        if not ready:
            await _record_run(conn, status="skipped-not-ready")
            return {"status": "skipped-not-ready"}

        # Run each ENABLED detector with isolation (R2.8 — one failure ≠ run failure).
        candidates = []
        suppressed: Dict[str, Any] = {}
        for det in DETECTORS:
            if not cfg.enabled(det.config_key):
                suppressed.setdefault("disabled", []).append(det.config_key)
                continue
            try:
                candidates.extend(await det.fn(conn, cfg))
            except Exception as e:
                logger.exception("insight detector %s failed", det.insight_type)
                suppressed.setdefault("errors", {})[det.insight_type] = str(e)

        new_ids = await upsert_candidates(conn, candidates, cfg)
        # Detected-but-not-newly-raised (already active / dismissed / actioned).
        suppressed["deduped_or_resolved"] = len(candidates) - len(new_ids)

        await _record_run(conn, status="ran", detected=len(candidates), suppressed=suppressed)
        return {
            "status": "ran",
            "detected": len(candidates),
            "new": len(new_ids),
            "new_ids": new_ids,
        }
