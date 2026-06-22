"""ai-finance-insights Task 5 — categorizer readiness watermark (R2.1).

The 02:30 categorizer writes a finance.job_runs 'completed' row on success (the
signal the nightly insight runner gates on); a failing run writes nothing.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
import backend.services.categorizer as categorizer
from backend.services.categorizer import run_categorizer
from backend.tests.semantic_helpers import apply_migrations


async def _watermark_count(pool) -> int:
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT count(*) FROM finance.job_runs "
            "WHERE job_name = 'categorizer' AND status = 'completed' AND ran_for = CURRENT_DATE"
        )


@pytest.mark.asyncio
async def test_success_writes_watermark(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        # Fresh DB → legacy path → "no uncategorized transactions" (a successful,
        # no-op run). Still a completed window, so the watermark must be written.
        result = await run_categorizer()
        assert result.get("status") == "skipped"  # no transactions to categorize
        assert await _watermark_count(pool) == 1
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_failure_writes_no_watermark(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async def _boom():
            raise RuntimeError("categorization exploded")

        monkeypatch.setattr(categorizer, "_run_legacy", _boom)
        with pytest.raises(RuntimeError):
            await run_categorizer()
        assert await _watermark_count(pool) == 0
    finally:
        await close_pool()
