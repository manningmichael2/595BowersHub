"""
Test fixtures for backend tests.

The suite assumes a reachable Postgres instance whose superuser-or-equivalent
credentials are passed in via env vars (DB_HOST/DB_PORT/DB_USER/DB_PASSWORD).
The defaults match the bowershub-ai docker stack's `postgres` service so the
suite runs out of the box from inside that container or from any host that
can reach the same network.

Each test that needs a database uses the `fresh_db` fixture, which:
  - connects to the maintenance DB (`postgres`) on the configured server
  - creates a uniquely-named ephemeral test database
  - yields its name (callers connect to it themselves)
  - drops the database after the test

This keeps the test fully isolated: no data is left behind, and the live
`finance` database used by the running app is never touched.
"""

from __future__ import annotations

import os
import secrets

import asyncpg
import pytest
import pytest_asyncio


def _db_settings() -> dict[str, str | int]:
    return {
        "host": os.environ.get("DB_HOST", "postgres"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "user": os.environ.get("DB_USER", "michael"),
        "password": os.environ.get("DB_PASSWORD", ""),
    }


@pytest.fixture
def fresh_db_name() -> str:
    """A random, valid Postgres identifier safe to use as a database name."""
    return f"bh_test_{secrets.token_hex(6)}"


@pytest_asyncio.fixture
async def fresh_db(fresh_db_name: str):
    """
    Create an empty Postgres database for the test, yield its name, then drop it.

    Yields the database name (str). Tests are expected to connect to it
    themselves using the same `_db_settings()` values.
    """
    settings = _db_settings()
    admin = await asyncpg.connect(database="postgres", **settings)
    try:
        # Quoted ident — name is hex-only so this is safe, but be explicit.
        await admin.execute(f'CREATE DATABASE "{fresh_db_name}"')
    finally:
        await admin.close()

    # Pre-create the pgvector extension, mirroring the production superuser cutover
    # (docs/semantic-memory-cutover.md): migration 0010 assumes `vector` already
    # exists and guards loudly otherwise. The suite therefore runs against a
    # pgvector-capable image (pgvector/pgvector:pg16). Tests that specifically
    # exercise the missing-extension guard drop it themselves.
    ext = await asyncpg.connect(database=fresh_db_name, **settings)
    try:
        await ext.execute("CREATE EXTENSION IF NOT EXISTS vector")
    finally:
        await ext.close()

    try:
        yield fresh_db_name
    finally:
        admin = await asyncpg.connect(database="postgres", **settings)
        try:
            # Terminate any stragglers so DROP doesn't block.
            await admin.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE datname = $1 AND pid <> pg_backend_pid()
                """,
                fresh_db_name,
            )
            await admin.execute(f'DROP DATABASE IF EXISTS "{fresh_db_name}"')
        finally:
            await admin.close()


@pytest.fixture
def db_settings() -> dict[str, str | int]:
    """Connection settings, exposed so tests can connect to fresh_db themselves."""
    return _db_settings()
