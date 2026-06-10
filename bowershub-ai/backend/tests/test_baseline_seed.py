"""
Smoke test for the squashed schema baseline (0001_baseline.sql).

Applies the migration chain to a freshly-created ephemeral database via the
real `database.run_migrations()` runner (which, on an empty DB, executes the
baseline), then asserts the seed/config data the baseline carries:
  - The baseline is recorded in `public.bh_migrations`.
  - Preset themes are seeded (incl. dark-navy), each with the 9 required tokens.
  - The 4 platform-settings rows are seeded.
  - default_theme_id points at the dark-navy preset.

This replaces the old per-migration (009/010) seed test: those migrations were
squashed into the baseline (project-review.md C2), so the assertions now target
the baseline's outcome rather than specific archived files.

Validates: Requirements R1.1, R3.7
"""

from __future__ import annotations

import asyncpg
import pytest

from backend.config import Config
from backend.database import close_pool, init_pool, run_migrations


pytestmark = pytest.mark.asyncio


async def _apply_migrations(db_name: str, db_settings: dict) -> asyncpg.Pool:
    """Initialize the project pool against `db_name` and run all migrations."""
    config = Config(
        ANTHROPIC_API_KEY="test",
        DB_HOST=str(db_settings["host"]),
        DB_PORT=int(db_settings["port"]),
        DB_NAME=db_name,
        DB_USER=str(db_settings["user"]),
        DB_PASSWORD=str(db_settings["password"]),
        JWT_SECRET="test",
        N8N_BASE="http://localhost:5678",
    )
    pool = await init_pool(config)
    await run_migrations(pool)
    return pool


async def test_baseline_seeds_themes_and_platform_settings(fresh_db, db_settings):
    """Apply the baseline to a fresh DB; verify themes, settings, and tracking rows."""
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # --- bh_migrations records the baseline ----------------------------
            applied = {
                row["filename"]
                for row in await conn.fetch(
                    "SELECT filename FROM public.bh_migrations"
                )
            }
            assert "0001_baseline.sql" in applied, (
                f"baseline not recorded in bh_migrations; got {sorted(applied)}"
            )

            # --- preset themes seeded, including dark-navy ---------------------
            theme_rows = await conn.fetch(
                """
                SELECT slug, name, tokens_json
                FROM public.bh_themes
                WHERE is_preset = true AND owner_id IS NULL
                ORDER BY id
                """
            )
            slugs = {row["slug"] for row in theme_rows}
            assert len(theme_rows) >= 4, (
                f"expected at least 4 preset themes, got {len(theme_rows)}"
            )
            assert "dark-navy" in slugs, f"dark-navy preset missing; got {slugs}"

            # --- tokens_json sanity: every preset has the 9 required tokens ----
            required_tokens = {
                "background", "surface", "primary", "accent", "text",
                "text_muted", "border", "danger", "success",
            }
            for row in theme_rows:
                tokens = row["tokens_json"]
                assert isinstance(tokens, dict), (
                    f"{row['slug']} tokens_json is {type(tokens).__name__}, not dict"
                )
                missing = required_tokens - set(tokens.keys())
                assert not missing, f"{row['slug']} missing tokens: {missing}"

            # --- platform settings seeded -------------------------------------
            keys = {
                row["key"]
                for row in await conn.fetch(
                    "SELECT key FROM public.bh_platform_settings"
                )
            }
            expected_keys = {
                "default_theme_id",
                "app_icon_version",
                "app_icon_active_filename",
                "app_icon_previous_filename",
            }
            assert expected_keys <= keys, (
                f"platform settings missing keys: {expected_keys - keys}"
            )

            # --- default_theme_id points at the dark-navy preset ---------------
            default_theme_id = await conn.fetchval(
                """
                SELECT (value_json->>'theme_id')::int
                FROM public.bh_platform_settings
                WHERE key = 'default_theme_id'
                """
            )
            dark_navy_id = await conn.fetchval(
                """
                SELECT id FROM public.bh_themes
                WHERE slug = 'dark-navy' AND owner_id IS NULL
                """
            )
            assert default_theme_id == dark_navy_id, (
                f"default_theme_id ({default_theme_id}) does not match "
                f"the dark-navy preset id ({dark_navy_id})"
            )
    finally:
        await close_pool()
