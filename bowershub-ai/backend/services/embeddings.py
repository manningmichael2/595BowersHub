"""
Embeddings Service: generates vector embeddings via local Ollama API.
"""

import logging
from typing import List, Optional

import httpx
from backend.http_client import get_http_client
from backend.services.model_catalog import resolve_role, get_embedding_config

logger = logging.getLogger(__name__)


class EmbeddingError(Exception):
    """Raised when the embedding API calls fail."""
    pass


class DimensionMismatchError(EmbeddingError):
    """Raised when the returned vector dimension does not match the configured one."""
    pass


class EmbeddingsClient:
    """
    Client for generating embeddings using a local Ollama server.
    
    Reuses the global HTTP client and resolves its configuration (model, dim)
    from the database-driven model catalog.
    
    Satisfies R1.1, R1.2, R2.7.
    """

    def __init__(self, base_url: str, pool):
        self.base_url = base_url.rstrip("/")
        self.pool = pool

    async def embed(self, text: str) -> List[float]:
        """Generate a single embedding for a string."""
        vectors = await self.embed_batch([text])
        return vectors[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generate embeddings for a list of strings in one call.
        
        Args:
            texts: List of strings to embed.
            
        Returns:
            List of embedding vectors (floats).
            
        Raises:
            EmbeddingError: if the API call fails.
            DimensionMismatchError: if the result has the wrong dimension.
        """
        if not texts:
            return []

        # Resolve current configuration from DB
        # Fresh each time to handle version/model cutovers (R3.4)
        config = await get_embedding_config(self.pool)
        model = resolve_role("embed")
        expected_dim = config.get("dim", 1024)

        url = f"{self.base_url}/api/embed"
        payload = {
            "model": model,
            "input": texts,
        }

        try:
            client = get_http_client()
            # Embeddings can take a while for large batches/models
            resp = await client.post(url, json=payload, timeout=60.0)
            
            if resp.status_code != 200:
                detail = resp.text[:500]
                # Check for "model not found" specifically
                if "not found" in detail.lower():
                    logger.error(f"Ollama embedding model '{model}' not pulled. Run 'ollama pull {model}'.")
                raise EmbeddingError(f"Ollama embed failed ({resp.status_code}): {detail}")
            
            data = resp.json()
            embeddings = data.get("embeddings", [])
            
            if not embeddings:
                # Handle legacy /api/embeddings response if needed
                # (deprecated, but some older Ollama versions might still use it)
                if "embedding" in data:
                    embeddings = [data["embedding"]]
                else:
                    raise EmbeddingError(f"Ollama returned no embeddings in response: {data}")

            # Validate dimensions (R2.7)
            for i, vec in enumerate(embeddings):
                if len(vec) != expected_dim:
                    raise DimensionMismatchError(
                        f"Vector dimension mismatch for '{model}': "
                        f"got {len(vec)}, expected {expected_dim}. "
                        "Check your embedding_config in bh_platform_settings."
                    )
            
            return embeddings

        except httpx.TimeoutException:
            raise EmbeddingError(f"Ollama embed timed out (60s) for model {model}")
        except httpx.RequestError as e:
            raise EmbeddingError(f"Ollama unreachable: {e}")
        except Exception as e:
            if isinstance(e, EmbeddingError):
                raise
            logger.exception("Unexpected error in EmbeddingsClient")
            raise EmbeddingError(f"Unexpected embedding error: {e}")
