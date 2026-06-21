"""Re-derive merchant keys after a normalization-rule change (0027). Run AFTER the
migration is applied. Re-keys transactions + the merchant_memory learning rows
(keyed on merchant_key) through the new rules, refreshes the merchant directory +
embeddings, and reports the singleton reduction. Idempotent.

merchant_memory has UNIQUE(merchant_key, category_id); if re-keying collides with
an existing (key, category) row their times_reinforced are summed and the dup
dropped, so no learning is lost."""
import asyncio
from collections import defaultdict

from backend.config import load_config
from backend.database import close_pool, get_pool, init_pool
from backend.http_client import close_http_client, init_http_client
from backend.services.categorization.knn import embed_merchants
from backend.services.embeddings import EmbeddingsClient
from backend.services.merchant_normalizer import backfill_merchant_keys, build_normalizer


async def main():
    await init_pool(load_config())
    init_http_client()
    try:
        pool = get_pool()

        def stats(rows):
            by = defaultdict(int)
            for r in rows:
                by[r["merchant_key"]] += 1
            return len(by), sum(1 for v in by.values() if v == 1)

        async with pool.acquire() as conn:
            before = await conn.fetch("SELECT merchant_key FROM finance.transactions WHERE merchant_key IS NOT NULL")
        bk, bs = stats(before)
        print(f"transactions before: {bk} keys, {bs} singletons", flush=True)

        # 1. Re-derive ALL transaction keys (only_missing=False).
        print("re-deriving transaction merchant_keys ...", flush=True)
        print("   ", await backfill_merchant_keys(only_missing=False), flush=True)

        # 2. Re-key merchant_memory through the new rules (merge on unique collision).
        async with pool.acquire() as conn:
            normalizer = await build_normalizer(conn)
            mem = await conn.fetch(
                "SELECT id, merchant_key, category_id, times_reinforced FROM finance.merchant_memory")
            rekeyed, merged = 0, 0
            for r in mem:
                new_key = normalizer.normalize(r["merchant_key"]).key
                if new_key == r["merchant_key"]:
                    continue
                async with conn.transaction():
                    existing = await conn.fetchrow(
                        "SELECT id FROM finance.merchant_memory WHERE merchant_key=$1 AND category_id=$2",
                        new_key, r["category_id"])
                    if existing:
                        await conn.execute(
                            "UPDATE finance.merchant_memory SET times_reinforced = times_reinforced + $1, "
                            "last_reinforced_at = now() WHERE id=$2", r["times_reinforced"], existing["id"])
                        await conn.execute("DELETE FROM finance.merchant_memory WHERE id=$1", r["id"])
                        merged += 1
                        print(f"   merge: {r['merchant_key']!r} -> {new_key!r} (cat {r['category_id']})", flush=True)
                    else:
                        await conn.execute(
                            "UPDATE finance.merchant_memory SET merchant_key=$1 WHERE id=$2", new_key, r["id"])
                        rekeyed += 1
                        print(f"   rekey: {r['merchant_key']!r} -> {new_key!r}", flush=True)
            print(f"merchant_memory: {rekeyed} rekeyed, {merged} merged", flush=True)

        # 3. Embed the (new) merchant keys for the kNN tier.
        print("embedding merchants ...", flush=True)
        client = EmbeddingsClient("http://ollama:11434", pool)
        print("   ", await embed_merchants(client, pool, only_missing=True), flush=True)

        # 4. Report orphaned directory rows (merchants no transaction references).
        async with pool.acquire() as conn:
            orphans = await conn.fetchval(
                "SELECT count(*) FROM finance.merchants m "
                "WHERE NOT EXISTS (SELECT 1 FROM finance.transactions t WHERE t.merchant_key=m.merchant_key)")
            after = await conn.fetch("SELECT merchant_key FROM finance.transactions WHERE merchant_key IS NOT NULL")
        ak, as_ = stats(after)
        print(f"\ntransactions after:  {ak} keys, {as_} singletons  (Δ keys {ak-bk}, Δ singletons {as_-bs})", flush=True)
        print(f"orphaned merchant directory rows (old keys, harmless): {orphans}", flush=True)
    finally:
        await close_http_client()
        await close_pool()


asyncio.run(main())
