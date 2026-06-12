"""Shared helpers for semantic-memory DB-backed tests (not collected as tests)."""

from __future__ import annotations

from typing import List, Optional, Sequence

import asyncpg

from backend.config import Config
from backend.database import init_pool, run_migrations
from backend.services.embeddings import EmbeddingError

DIM = 1024


def config_for(db_name: str, db_settings: dict) -> Config:
    return Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]), DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name, DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test", N8N_BASE="http://localhost:5678",
    )


async def apply_migrations(db_name: str, db_settings: dict) -> asyncpg.Pool:
    pool = await init_pool(config_for(db_name, db_settings))
    await run_migrations(pool)
    return pool


async def seed_user_and_conversation(conn, *, workspace_id: int = 1) -> int:
    """Create an admin user + a conversation in `workspace_id`; return conversation id.
    Workspaces (incl. id=1 General) are seeded by the baseline."""
    uid = await conn.fetchval(
        """
        INSERT INTO public.bh_users (email, password_hash, display_name, role)
        VALUES ('embed-test@example.com', 'x', 'Embed Test', 'admin')
        RETURNING id
        """
    )
    conv = await conn.fetchval(
        "INSERT INTO public.bh_conversations (workspace_id, user_id, title) VALUES ($1,$2,'t') RETURNING id",
        workspace_id, uid,
    )
    return conv


async def add_message(conn, conv_id: int, role: str, content: str) -> int:
    return await conn.fetchval(
        "INSERT INTO public.bh_messages (conversation_id, role, content) VALUES ($1,$2,$3) RETURNING id",
        conv_id, role, content,
    )


async def add_entity(conn, name: str, summary: str, *, entity_type: str = "fact") -> int:
    return await conn.fetchval(
        """
        INSERT INTO public.bh_entities (name, entity_type, summary)
        VALUES ($1,$2,$3) RETURNING id
        """,
        name, entity_type, summary,
    )


class FakeEmbeddingsClient:
    """Deterministic, network-free stand-in for EmbeddingsClient (Gemini's API:
    embed(text)->vec, embed_batch(texts)->[vec]).

    Encodes each text into a `dim`-length vector so distinct texts get distinct,
    non-degenerate vectors. `fail=True` makes both raise (R2.7/degrade tests).
    `vector_for` lets a test pin an exact vector for a known text (retrieval tests)."""

    def __init__(self, dim: int = DIM):
        self.dim = dim
        self.fail = False
        self.calls: List[List[str]] = []
        self.vector_for: dict[str, List[float]] = {}

    def _encode(self, text: str) -> List[float]:
        if text in self.vector_for:
            v = list(self.vector_for[text])
            return v + [0.0] * (self.dim - len(v)) if len(v) < self.dim else v[: self.dim]
        v = [0.0] * self.dim
        # spread a few non-zero components derived from the text so norms are nonzero
        v[0] = float((len(text) % 97) + 1)
        v[1] = float((sum(ord(c) for c in text) % 89) + 1)
        v[2] = 1.0
        return v

    async def embed_batch(self, texts: Sequence[str]) -> List[List[float]]:
        if self.fail:
            raise EmbeddingError("fake ollama down")
        self.calls.append(list(texts))
        return [self._encode(t) for t in texts]

    async def embed(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]
