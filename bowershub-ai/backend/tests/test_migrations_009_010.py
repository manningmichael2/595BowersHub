"""
Migration smoke test for 009_themes_and_branding.sql and
010_settings_json_keys.sql.

Applies the project's full migration chain to a freshly-created ephemeral
database via the existing `database.run_migrations()` runner, then asserts:
  - Both migrations are recorded in `public.bh_migrations`.
  - 4 preset rows exist in `public.bh_themes`
    (Dark Navy, Light Stone, Forest, Mono — all with is_preset=true,
    owner_id IS NULL).
  - 4 platform settings rows exist in `public.bh_platform_settings`
    (default_theme_id, app_icon_version, app_icon_active_filename,
    app_icon_previous_filename).
  - default_theme_id points at the dark-navy preset.

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


async def test_migrations_009_010_seed_themes_and_platform_settings(
    fresh_db, db_settings
):
    """Apply migrations to a fresh DB; verify themes, settings, and tracking rows."""
    pool = await _apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            # --- bh_migrations records both files ------------------------------
            applied = {
                row["filename"]
                for row in await conn.fetch(
                    "SELECT filename FROM public.bh_migrations"
                )
            }
            assert "009_themes_and_branding.sql" in applied, (
                f"009 not recorded in bh_migrations; got {sorted(applied)}"
            )
            assert "010_settings_json_keys.sql" in applied, (
                f"010 not recorded in bh_migrations; got {sorted(applied)}"
            )

            # --- 4 preset themes seeded ----------------------------------------
            theme_rows = await conn.fetch(
                """
                SELECT slug, name, is_preset, owner_id
                FROM public.bh_themes
                WHERE is_preset = true AND owner_id IS NULL
                ORDER BY id
                """
            )
            slugs = {row["slug"] for row in theme_rows}
            expected_slugs = {"dark-navy", "light-stone", "forest", "mono"}
            assert len(theme_rows) == 4, (
                f"expected 4 preset theme rows, got {len(theme_rows)}: "
                f"{[(r['slug'], r['name']) for r in theme_rows]}"
            )
            assert slugs == expected_slugs, (
                f"preset slugs mismatch — expected {expected_slugs}, got {slugs}"
            )

            # --- tokens_json sanity: every preset has the 9 required tokens ----
            token_payloads = await conn.fetch(
                "SELECT slug, tokens_json FROM public.bh_themes WHERE is_preset = true"
            )
            required_tokens = {
                "background", "surface", "primary", "accent", "text",
                "text_muted", "border", "danger", "success",
            }
            for row in token_payloads:
                tokens = row["tokens_json"]
                assert isinstance(tokens, dict), (
                    f"{row['slug']} tokens_json is {type(tokens).__name__}, "
                    f"not dict"
                )
                missing = required_tokens - set(tokens.keys())
                assert not missing, (
                    f"{row['slug']} missing tokens: {missing}"
                )

            # --- 4 platform settings seeded ------------------------------------
            settings_rows = await conn.fetch(
                "SELECT key, value_json FROM public.bh_platform_settings ORDER BY key"
            )
            keys = {row["key"] for row in settings_rows}
            expected_keys = {
                "default_theme_id",
                "app_icon_version",
                "app_icon_active_filename",
                "app_icon_previous_filename",
            }
            assert len(settings_rows) == 4, (
                f"expected 4 platform settings rows, got {len(settings_rows)}: "
                f"{[r['key'] for r in settings_rows]}"
            )
            assert keys == expected_keys, (
                f"platform settings keys mismatch — expected {expected_keys}, "
                f"got {keys}"
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
