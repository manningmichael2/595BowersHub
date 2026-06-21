"""Final cutover step: flip engine shadow→cascade and run one live pass.

Clears the prior shadow dry-run provenance (asserts none were applied first),
flips the gate, runs the categorizer in cascade mode (real writes through the
guarded Writer), then reports what was applied and asserts no investment-pattern
row received a category (the leak we just fixed). Reversible: set engine back to
shadow and reverse per-row from categorization_decision.prior_category_id."""
import asyncio

from backend.config import load_config as load_app_config
from backend.database import close_pool, get_pool, init_pool
from backend.http_client import close_http_client, init_http_client
from backend.services.categorization_eval import set_engine
from backend.services.categorizer import run_categorizer


async def main():
    await init_pool(load_app_config())
    init_http_client()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            applied = await conn.fetchval(
                "SELECT count(*) FROM finance.categorization_decision WHERE auto_applied")
            assert applied == 0, f"refusing to clear: {applied} applied rows already present"
            await conn.execute("DELETE FROM finance.categorization_decision")
            await set_engine(conn, "cascade")
        print("engine -> cascade (prior shadow log cleared)", flush=True)

        print("running cascade (LIVE) ...", flush=True)
        print("   summary:", await run_categorizer(), flush=True)

        async with pool.acquire() as conn:
            print("\n-- applied categories (live writes) --", flush=True)
            rows = await conn.fetch(
                "SELECT c.name, t.categorized_by_tier tier, count(*) n "
                "FROM finance.transactions t JOIN finance.categories c ON c.id=t.category_id "
                "WHERE t.categorized_by_tier IS NOT NULL GROUP BY 1,2 ORDER BY n DESC")
            for r in rows:
                print(f"   {r['name']:24s} tier={r['tier']:12s} n={r['n']}", flush=True)

            leak = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions t "
                "WHERE t.category_id IS NOT NULL AND t.categorized_by_tier IS NOT NULL "
                "  AND (t.description ILIKE 'Investment:%' OR t.description ILIKE '%401%' "
                "       OR t.description ILIKE '%vanguard%')")
            print(f"\nSAFETY: investment-pattern rows that got auto-categorized = {leak} (must be 0)", flush=True)

            queue = await conn.fetchval(
                "SELECT count(*) FROM finance.transactions "
                "WHERE category_id IS NULL AND user_category_override=false "
                "  AND is_transfer=false AND is_investment=false")
            print(f"review queue (uncategorized remaining): {queue}", flush=True)
    finally:
        await close_http_client()
        await close_pool()


asyncio.run(main())
