"""
EmbeddingsClient — unit tests (R1.1, R2.7).

Network-free via httpx.MockTransport injected through the patched get_http_client
singleton. Covers: batched success, dim-mismatch rejection, HTTP error and
transport error both surfacing as EmbeddingError (no silent drop).
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.services.embeddings import (
    DimensionMismatchError,
    EmbeddingError,
    EmbeddingsClient,
)

pytestmark = pytest.mark.asyncio

DIM = 4


@contextmanager
def _mocked(handler, dim=DIM):
    """Patch the http client singleton + DB-driven config so embed() runs offline."""
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with patch("backend.services.embeddings.get_http_client", return_value=client), \
         patch("backend.services.embeddings.get_embedding_config", AsyncMock(return_value={"dim": dim})), \
         patch("backend.services.embeddings.resolve_role", return_value="bge-m3"):
        yield


async def test_embed_batch_success_in_order():
    def handler(request):
        body = json.loads(request.content)
        return httpx.Response(200, json={"embeddings": [[float(len(t)), 0.0, 0.0, 0.0] for t in body["input"]]})

    with _mocked(handler):
        out = await EmbeddingsClient("http://ollama", pool=None).embed_batch(["a", "bbb"])
    assert [v[0] for v in out] == [1.0, 3.0]


async def test_dimension_mismatch_rejected():
    def handler(request):
        return httpx.Response(200, json={"embeddings": [[1.0, 2.0, 3.0]]})  # 3 != 4

    with _mocked(handler):
        with pytest.raises(DimensionMismatchError):
            await EmbeddingsClient("http://ollama", pool=None).embed("x")


async def test_http_error_surfaces():
    def handler(request):
        return httpx.Response(503, text="model not loaded")

    with _mocked(handler):
        with pytest.raises(EmbeddingError):
            await EmbeddingsClient("http://ollama", pool=None).embed("x")


async def test_transport_error_surfaces():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with _mocked(handler):
        with pytest.raises(EmbeddingError):
            await EmbeddingsClient("http://ollama", pool=None).embed("x")


async def test_empty_input_is_noop():
    def handler(request):  # pragma: no cover
        raise AssertionError("should not call Ollama for empty input")

    with _mocked(handler):
        assert await EmbeddingsClient("http://ollama", pool=None).embed_batch([]) == []
