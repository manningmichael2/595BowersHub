"""
Database connection pool and migration runner.
Uses asyncpg for async Postgres access.
"""

import hashlib
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


# The schema was squashed into this baseline (project-review.md C2). It is the
# single source of truth for building the schema from an empty database; the
# pre-baseline granular migrations live under migrations/_archive/ and are not
# re-run. Forward-only migrations follow as 0002_*.sql, 0003_*.sql, ...
BASELINE_FILENAME = "0001_baseline.sql"


def _checksum(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def run_migrations(pool: asyncpg.Pool):
    """
    Apply pending SQL migrations from backend/migrations/ in filename order.

    Tracks applied migrations (with content checksums) in public.bh_migrations.
    Files in subdirectories (e.g. migrations/_archive/) are ignored.

    Baseline reconciliation: a database that predates the squashed baseline was
    built by the old granular chain and already has the full schema, so the
    baseline must be *adopted* (recorded as applied) rather than executed. We
    detect such a database by the presence of a core table the old chain
    created (public.bh_users). A genuinely empty database has no bh_users, so
    the baseline runs normally and builds everything.
    """
    migrations_dir = Path(__file__).parent / "migrations"

    async with pool.acquire() as conn:
        # Ensure tracking table exists, and add the checksum column on upgrade.
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS public.bh_migrations (
                id          SERIAL PRIMARY KEY,
                filename    TEXT NOT NULL UNIQUE,
                checksum    TEXT,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        await conn.execute(
            "ALTER TABLE public.bh_migrations ADD COLUMN IF NOT EXISTS checksum TEXT"
        )

        # filename -> checksum (checksum may be NULL for pre-checksum rows)
        rows = await conn.fetch("SELECT filename, checksum FROM public.bh_migrations")
        applied = {row["filename"]: row["checksum"] for row in rows}

        # Discover top-level migration files only (ignore _archive/ subdir).
        migration_files = sorted(
            f for f in migrations_dir.iterdir()
            if f.is_file() and f.suffix == ".sql" and f.name != ".gitkeep"
        )

        # --- Baseline reconciliation -------------------------------------
        baseline = migrations_dir / BASELINE_FILENAME
        if baseline.exists() and BASELINE_FILENAME not in applied:
            already_built = await conn.fetchval("SELECT to_regclass('public.bh_users')")
            if already_built is not None:
                checksum = _checksum(baseline.read_text())
                await conn.execute(
                    "INSERT INTO public.bh_migrations (filename, checksum) VALUES ($1, $2)",
                    BASELINE_FILENAME, checksum,
                )
                applied[BASELINE_FILENAME] = checksum
                logger.info(
                    f"  ↺ adopted existing schema as baseline ({BASELINE_FILENAME}); not re-run"
                )

        # --- Drift detection on already-applied migrations ---------------
        for f in migration_files:
            recorded = applied.get(f.name)
            if recorded and _checksum(f.read_text()) != recorded:
                logger.warning(
                    f"  ⚠ migration {f.name} changed since it was applied "
                    "(checksum drift — applied migrations are immutable)"
                )

        # --- Apply pending migrations ------------------------------------
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
                        "INSERT INTO public.bh_migrations (filename, checksum) VALUES ($1, $2)",
                        migration_file.name, _checksum(sql),
                    )
                logger.info(f"  ✓ {migration_file.name} applied")
            except Exception as e:
                logger.error(f"  ✗ Migration {migration_file.name} failed: {e}")
                raise SystemExit(f"Migration failed: {migration_file.name} — {e}")

        logger.info(f"Applied {len(pending)} migration(s)")
