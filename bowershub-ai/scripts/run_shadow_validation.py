"""Cutover step 4: flip engine legacy→shadow, run the cascade as a dry run
(provenance only, NO category/is_transfer writes — verified in Writer.apply), and
report what it WOULD do from the authoritative decision log. Reversible: the engine
can be set back to 'legacy' and the decision rows are logs, not user data."""
import asyncio

from backend.config import load_config as load_app_config
from backend.database import close_pool, get_pool, init_pool
from backend.http_client import close_http_client, init_http_client
from backend.services.categorization_eval import set_engine
from backend.services.categorization.orchestrator import categorization_metrics
from backend.services.categorizer import run_categorizer


async def main():
    await init_pool(load_app_config())
    init_http_client()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await set_engine(conn, "shadow")
        print("engine -> shadow", flush=True)

        print("running cascade (shadow) ...", flush=True)
        summary = await run_categorizer()
        print("   summary:", summary, flush=True)

        async with pool.acquire() as conn:
            print("\nmetrics (from decision log):", await categorization_metrics(conn), flush=True)
            print("\nwould-be transfer flags (tier=transfer, is_transfer_set):", flush=True)
            rows = await conn.fetch(
                "SELECT transaction_id, confidence, rationale FROM finance.categorization_decision "
                "WHERE is_transfer_set AND tier='transfer' ORDER BY decided_at DESC LIMIT 50")
            for r in rows:
                print(f"   txn={r['transaction_id']} conf={r['confidence']} {dict(r['rationale'])}", flush=True)
    finally:
        await close_http_client()
        await close_pool()


asyncio.run(main())
