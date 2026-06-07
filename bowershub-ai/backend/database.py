"""
Database connection pool and migration runner.
Uses asyncpg for async Postgres access.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

import asyncpg

from backend.config import Config

logger = logging.getLogger(__name__)

# Global pool reference
_pool: Optional[asyncpg.Pool] = None


async def _init_connection(conn: asyncpg.Connection):
    """Register codecs for JSON/JSONB so asyncpg returns native dict/list
    instead of raw strings on read. Without this, Pydantic 2.13+ rejects
    JSONB columns (sees '{}' as str, not dict).

    On the encode side, we accept either a Python object (encode via
    json.dumps) or an already-serialized JSON string (pass through). This
    keeps existing call sites that pass `json.dumps(...)` plus an `::jsonb`
    cast working unchanged.
    """
    def _encode(value):
        if isinstance(value, (str, bytes)):
            return value if isinstance(value, str) else value.decode()
        return json.dumps(value)

    await conn.set_type_codec(
        "jsonb", encoder=_encode, decoder=json.loads, schema="pg_catalog"
    )
    await conn.set_type_codec(
        "json", encoder=_encode, decoder=json.loads, schema="pg_catalog"
    )


async def init_pool(config: Config) -> asyncpg.Pool:
    """Initialize the asyncpg connection pool."""
    global _pool
    _pool = await asyncpg.create_pool(
        host=config.DB_HOST,
        port=config.DB_PORT,
        database=config.DB_NAME,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        min_size=2,
        max_size=20,
        init=_init_connection,
    )
    logger.info(f"Database pool initialized (min=2, max=20) → {config.DB_HOST}:{config.DB_PORT}/{config.DB_NAME}")
    return _pool


async def close_pool():
    """Close the connection pool."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("Database pool closed")


def get_pool() -> asyncpg.Pool:
    """Get the active connection pool. Raises if not initialized."""
    if _pool is None:
        raise RuntimeError("Database pool not initialized. Call init_pool() first.")
    return _pool


async def run_migrations(pool: asyncpg.Pool):
    """
    Apply pending SQL migrations from backend/migrations/ directory.
    Tracks applied migrations in the bh_migrations table.
    Migrations are applied in filename sort order.
    """
    migrations_dir = Path(__file__).parent / "migrations"

    async with pool.acquire() as conn:
        # Ensure tracking table exists
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS public.bh_migrations (
                id          SERIAL PRIMARY KEY,
                filename    TEXT NOT NULL UNIQUE,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)

        # Get already-applied migrations
        applied = set()
        rows = await conn.fetch("SELECT filename FROM public.bh_migrations ORDER BY filename")
        for row in rows:
            applied.add(row["filename"])

        # Find and apply pending migrations
        migration_files = sorted(
            f for f in migrations_dir.iterdir()
            if f.suffix == ".sql" and f.name != ".gitkeep"
        )

        pending = [f for f in migration_files if f.name not in applied]

        if not pending:
            logger.info("No pending migrations")
            return

        for migration_file in pending:
            logger.info(f"Applying migration: {migration_file.name}")
            sql = migration_file.read_text()

            try:
                # Execute migration in a transaction
                async with conn.transaction():
                    await conn.execute(sql)
                    await conn.execute(
                        "INSERT INTO public.bh_migrations (filename) VALUES ($1)",
                        migration_file.name,
                    )
                logger.info(f"  ✓ {migration_file.name} applied")
            except Exception as e:
                logger.error(f"  ✗ Migration {migration_file.name} failed: {e}")
                raise SystemExit(f"Migration failed: {migration_file.name} — {e}")

        logger.info(f"Applied {len(pending)} migration(s)")
