"""Cutover step 1 (embeddings only): populate category + merchant bge-m3 vectors.
Split out from reconcile_cascade_inputs.py because EmbeddingsClient uses the shared
HTTP client, which a standalone script must init explicitly. Idempotent."""
import asyncio

from backend.config import load_config
from backend.database import close_pool, get_pool, init_pool
from backend.http_client import close_http_client, init_http_client
from backend.services.categorization.knn import embed_categories, embed_merchants
from backend.services.embeddings import EmbeddingsClient


async def main():
    await init_pool(load_config())
    init_http_client()
    try:
        pool = get_pool()
        client = EmbeddingsClient("http://ollama:11434", pool)
        print("embed_categories ...", flush=True)
        print("   ", await embed_categories(client, pool), flush=True)
        print("embed_merchants ...", flush=True)
        print("   ", await embed_merchants(client, pool, only_missing=True), flush=True)
    finally:
        await close_http_client()
        await close_pool()


asyncio.run(main())
