"""
Pure-unit tests for semantic-memory helpers.

The worker, retriever, and embeddings-client behaviour is covered by real-DB /
real-transport integration suites:
  - test_embedding_worker.py     (reconcile, retry, dead-letter, reap — real DB)
  - test_hybrid_retrieval.py     (RRF, workspace scoping, FTS degrade — real DB)
  - test_embeddings_client.py    (dim check, error surfacing — real transport)
This file keeps only the network/DB-free unit checks.
"""

import pytest

from backend.services.embedding_worker import compute_hash

pytestmark = pytest.mark.asyncio


async def test_compute_hash_is_stable_sha256():
    h1 = compute_hash("hello world")
    h2 = compute_hash("hello world")
    assert h1 == h2 and len(h1) == 64
    assert compute_hash("hello world") != compute_hash("hello world!")
