"""One-off cutover step 1: reconcile the categorization cascade's inputs against
the live finance DB. Mirrors the nightly `categorization_warmup` job plus the
historical `backfill_merchant_keys` (which the warmup omits — keys are normally
derived on SimpleFin ingest, so pre-existing history needs a one-time pass).

All four steps are idempotent. Run inside the bowershub-ai container (has DB env +
the ollama network)."""
import asyncio

from backend.config import load_config
from backend.database import close_pool, get_pool, init_pool
from backend.services.categorization.knn import embed_categories, embed_merchants
from backend.services.categorization.transfer_backfill import backfill_transfer_flags
from backend.services.embeddings import EmbeddingsClient
from backend.services.merchant_normalizer import backfill_merchant_keys


async def main():
    await init_pool(load_config())
    try:
        pool = get_pool()
        client = EmbeddingsClient("http://ollama:11434", pool)
        print("1/4 backfill_merchant_keys ...", flush=True)
        print("   ", await backfill_merchant_keys(only_missing=True), flush=True)
        print("2/4 embed_categories ...", flush=True)
        print("   ", await embed_categories(client, pool), flush=True)
        print("3/4 embed_merchants ...", flush=True)
        print("   ", await embed_merchants(client, pool, only_missing=True), flush=True)
        print("4/4 backfill_transfer_flags ...", flush=True)
        print("   ", await backfill_transfer_flags(), flush=True)
    finally:
        await close_pool()


asyncio.run(main())
