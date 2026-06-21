"""Re-validate the cascade in shadow after the investment-leak fix. Clears the
prior dry-run decision log (shadow provenance only — verified auto_applied=false),
re-runs the cascade (shadow → no writes), and reports per-tier decisions, what
WOULD auto-apply (confidence >= per-tier threshold), and any residual
investment-description rows still landing on Income."""
import asyncio

from backend.config import load_config as load_app_config
from backend.database import close_pool, get_pool, init_pool
from backend.http_client import close_http_client, init_http_client
from backend.services.categorization.config import load_config as load_cat_config
from backend.services.categorization.orchestrator import categorization_metrics
from backend.services.categorizer import run_categorizer


async def main():
    await init_pool(load_app_config())
    init_http_client()
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            applied = await conn.fetchval(
                "SELECT count(*) FROM finance.categorization_decision WHERE auto_applied")
            assert applied == 0, f"refusing to clear: {applied} applied rows present"
            await conn.execute("DELETE FROM finance.categorization_decision")
        print("cleared prior shadow decision log", flush=True)

        print("running cascade (shadow) ...", flush=True)
        print("   summary:", await run_categorizer(), flush=True)

        async with pool.acquire() as conn:
            cfg = await load_cat_config(conn)
            tau = cfg.thresholds
            print("\nthresholds:", tau, flush=True)
            print("metrics:", await categorization_metrics(conn), flush=True)

            print("\n-- would auto-apply (conf >= tier threshold) by category --", flush=True)
            rows = await conn.fetch(
                "SELECT d.tier, c.name, count(*) n, round(min(d.confidence),2) minc "
                "FROM finance.categorization_decision d "
                "LEFT JOIN finance.categories c ON c.id=d.applied_category_id "
                "WHERE d.applied_category_id IS NOT NULL GROUP BY 1,2 ORDER BY n DESC")
            for r in rows:
                t = tau.get(r["tier"], 1.0)
                mark = "AUTO" if float(r["minc"]) >= t else "queue"
                print(f"   [{mark}] tier={r['tier']:14s} {r['name']:22s} n={r['n']} minconf={r['minc']} (tau={t})", flush=True)

            print("\n-- residual investment-description rows landing on Income --", flush=True)
            bad = await conn.fetch(
                "SELECT round(d.confidence,2) conf, left(t.description,50) descr "
                "FROM finance.categorization_decision d "
                "JOIN finance.transactions t ON t.id=d.transaction_id "
                "JOIN finance.categories c ON c.id=d.applied_category_id "
                "WHERE c.name='Income' AND (t.description ILIKE '%invest%' OR t.description ILIKE '%401%' "
                "  OR t.description ILIKE '%vanguard%' OR t.description ILIKE '%ira%') "
                "ORDER BY d.confidence DESC")
            if not bad:
                print("   NONE", flush=True)
            for r in bad:
                print(f"   conf={r['conf']}  {r['descr']!r}", flush=True)
    finally:
        await close_http_client()
        await close_pool()


asyncio.run(main())
