"""
Regression test for the migration/runtime privilege split (project-review.md C1/C7).

This is the test that would have caught the 2026-06-19 deploy crash-loop. The
existing backend suite runs migrations as the cluster superuser (`michael`), so
it never exercised the scoped, non-superuser deploy path — which is exactly why
CI stayed green while prod crash-looped with "must be owner of view transactions".

Here we reproduce the PROD topology on the ephemeral test cluster:
  - runtime pool  → bowershub_app      (LOGIN, NOSUPERUSER) = DB_USER
  - migrations    → bowershub_migrator (LOGIN, SUPERUSER)   = MIGRATION_DB_USER

and assert the real deploy path works end to end:
  1. run_migrations() applies the full baseline→head chain via the elevated
     migration connection (the scoped pool alone could not — it can't
     CREATE EXTENSION / own legacy objects).
  2. Objects are owned by the migrator, proving the elevated connection (not the
     scoped pool) ran the DDL. If anyone later drops the split, this fails.
  3. The scoped runtime role can actually read app data across schemas — i.e.
     the grants that migrations set up reach the role the app connects as.

See docs/c7-db-roles-cutover.md.

Validates: project-review.md C1, C7
"""

from __future__ import annotations

import asyncpg
import pytest

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations

pytestmark = pytest.mark.asyncio

APP_ROLE = "bowershub_app"
APP_PW = "ci_app_pw"
MIGRATOR_ROLE = "bowershub_migrator"
MIGRATOR_PW = "ci_migrator_pw"


async def _provision_roles(db_name: str, db_settings: dict) -> None:
    """As the cluster superuser, ensure the prod-like roles exist with the
    attributes and passwords this test connects with. Roles are cluster-global,
    so creation is guarded and attributes/passwords are (re)set every run."""
    su = await asyncpg.connect(
        host=str(db_settings["host"]),
        port=int(db_settings["port"]),
        database=db_name,
        user=str(db_settings["user"]),
        password=str(db_settings["password"]),
    )
    try:
        await su.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                    CREATE ROLE {APP_ROLE};
                END IF;
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{MIGRATOR_ROLE}') THEN
                    CREATE ROLE {MIGRATOR_ROLE};
                END IF;
            END $$;
            """
        )
        # Scoped runtime role: can log in, NOT superuser. CREATEROLE because
        # migration 0002 (run historically as this role on prod) creates roles;
        # here migrations run as the migrator, but keep parity with prod attrs.
        await su.execute(
            f"ALTER ROLE {APP_ROLE} WITH LOGIN NOSUPERUSER CREATEROLE PASSWORD '{APP_PW}'"
        )
        # Migration role: elevated.
        await su.execute(
            f"ALTER ROLE {MIGRATOR_ROLE} WITH LOGIN SUPERUSER PASSWORD '{MIGRATOR_PW}'"
        )
    finally:
        await su.close()


async def test_deploy_path_migrate_as_app_role(fresh_db, db_settings):
    """Migrations apply via the elevated role while the runtime pool stays scoped."""
    await _provision_roles(fresh_db, db_settings)

    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=fresh_db,
        DB_USER=APP_ROLE,
        DB_PASSWORD=APP_PW,
        MIGRATION_DB_USER=MIGRATOR_ROLE,
        MIGRATION_DB_PASSWORD=MIGRATOR_PW,
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
    )
    # Sanity: this config must take the dedicated-migrator branch, else the test
    # would silently fall back to running migrations through the (scoped) pool.
    assert config.uses_dedicated_migration_role

    pool = await init_pool(config)  # connects as the scoped APP_ROLE
    try:
        # 1. The full chain applies through the elevated migration connection.
        #    On the scoped pool alone this would fail (no CREATE EXTENSION, no
        #    ownership of legacy objects) — that was the prod crash.
        await run_migrations(pool, config)

        async with pool.acquire() as conn:
            assert await conn.fetchval("SELECT current_user") == APP_ROLE

            applied = {
                row["filename"]
                for row in await conn.fetch("SELECT filename FROM public.bh_migrations")
            }
            assert "0001_baseline.sql" in applied
            assert "0021_migration_role.sql" in applied

            # 2. DDL ran as the migrator, not the scoped pool.
            owner = await conn.fetchval(
                "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'bh_users'"
            )
            assert owner == MIGRATOR_ROLE, (
                f"bh_users owned by {owner!r}, expected {MIGRATOR_ROLE!r} — the "
                "elevated migration connection did not run the DDL (privilege "
                "split regressed)."
            )

            # 3. The scoped runtime role can actually read app data — i.e. the
            #    grants migrations set up reach the role the app connects as.
            #    (These run AS the scoped pool, so a missing grant raises.)
            assert await conn.fetchval("SELECT count(*) FROM public.bh_users") >= 0
            assert await conn.fetchval("SELECT count(*) FROM finance.transactions") >= 0

            # Defense-in-depth: the runtime role really is not a superuser.
            assert await conn.fetchval(
                "SELECT rolsuper FROM pg_roles WHERE rolname = current_user"
            ) is False
    finally:
        await close_pool()
