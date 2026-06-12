import httpx
from contextlib import asynccontextmanager

_client: httpx.AsyncClient | None = None

def init_http_client() -> None:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=30.0)

async def close_http_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None

def get_http_client() -> httpx.AsyncClient:
    if _client is None:
        raise RuntimeError("HTTP client is not initialized. Call init_http_client() first.")
    return _client

@asynccontextmanager
async def get_http_session():
    """
    Context manager that yields the global shared HTTP client.
    Does NOT close the client on exit, allowing it to be reused.
    Enables surgical replacement of 'async with httpx.AsyncClient()'.
    """
    yield get_http_client()
