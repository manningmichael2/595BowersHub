"""authz core — DB-backed tests (throwaway pgvector pg16).

Verifies the 0039 seed, that authz.reload() reflects a row change with no
restart (R1.3 end-to-end), and the boot self-check's fail-closed behavior.
"""

from __future__ import annotations

import pytest

from backend.database import close_pool
from backend.services import authz
from backend.services.authz import _DEFAULT_CAPS
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_0039_seed_matches_default_caps(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        await authz.init_authz(pool)
        seeded = authz.get_cache().all_capabilities()
        # Every code-fallback capability is seeded with the same min_role.
        for cap, role in _DEFAULT_CAPS.items():
            assert seeded.get(cap) == role, f"{cap}: seed {seeded.get(cap)!r} != {role!r}"
        assert authz.get_cache().known_capabilities() >= set(_DEFAULT_CAPS)
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_reload_reflects_retune_without_restart(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        await authz.init_authz(pool)
        member = {"role": "member"}
        # Seeded admin-only — member denied.
        assert authz.resolve(member, "finance.delete") is False

        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE public.bh_capabilities SET min_role='member' WHERE capability='finance.delete'"
            )
        # Still denied until reload (cache is authoritative).
        assert authz.resolve(member, "finance.delete") is False

        await authz.reload()
        assert authz.resolve(member, "finance.delete") is True
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_boot_self_check_fails_on_unregistered_capability(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        await authz.init_authz(pool)
        # A live gate references a capability with no bh_capabilities row.
        monkeypatch.setattr(authz, "_REGISTERED_CAPABILITIES", {"ghost.capability"})
        with pytest.raises(SystemExit) as exc:
            await authz.verify_registered_capabilities()
        assert "ghost.capability" in str(exc.value)
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_boot_self_check_passes_for_seeded_capabilities(fresh_db, db_settings, monkeypatch):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        await authz.init_authz(pool)
        monkeypatch.setattr(authz, "_REGISTERED_CAPABILITIES", {"finance.write", "users.manage"})
        await authz.verify_registered_capabilities()  # no raise
    finally:
        await close_pool()
