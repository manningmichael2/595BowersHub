"""One-time full-history investment backfill. The ingest-time call uses a narrow
window (and was crashing on the int[] cast), so older/leaked investment rows were
never flagged. Run AFTER the cast fix is in place. Idempotent (only touches
is_investment=false rows). Reports before/after counts."""
import asyncio

from backend.config import load_config
from backend.database import close_pool, get_pool, init_pool
from backend.services.investment_detector import flag_investments_in_db


async def main():
    await init_pool(load_config())
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            before = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions WHERE is_investment=true")
            leak = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions "
                "WHERE description ILIKE 'Investment:%' AND is_investment=false")
        print(f"before: is_investment=true {before}, investment-pattern-but-unflagged {leak}", flush=True)

        # Wide window to sweep all of history once.
        result = await flag_investments_in_db(window_days=4000)
        print("flag result:", result, flush=True)

        async with pool.acquire() as conn:
            after = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions WHERE is_investment=true")
            still = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions "
                "WHERE description ILIKE 'Investment:%' AND is_investment=false")
        print(f"after:  is_investment=true {after}, investment-pattern-but-unflagged {still}", flush=True)
    finally:
        await close_pool()


asyncio.run(main())
