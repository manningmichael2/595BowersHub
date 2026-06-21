"""DB-driven per-skill min_role gate (0028) — replaces the hardcoded
ADMIN_ONLY_SKILLS set. Verifies the seed and the role-rank check.
"""

from __future__ import annotations

import pytest

from backend.config import Config
from backend.database import close_pool
from backend.services.skill_executor import ROLE_RANK, SkillExecutor
from backend.tests.semantic_helpers import apply_migrations


@pytest.mark.asyncio
async def test_0028_seeds_admin_min_role_for_sql_skills(fresh_db, db_settings):
    """`ask-db` (the real SQL-executing skill) keeps admin-only behavior via
    min_role. `finance-query` was a dead entry in the old hardcoded set — it isn't
    seeded anywhere — so the migration's guarded UPDATE is a no-op for it; if it's
    ever created it must set its own min_role (the DB-driven contract)."""
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            askdb = await conn.fetchval(
                "SELECT min_role FROM public.bh_skills WHERE name = 'ask-db'")
            finance_query = await conn.fetchval(
                "SELECT count(*) FROM public.bh_skills WHERE name = 'finance-query'")
        assert askdb == "admin", f"ask-db should be admin-gated, got {askdb!r}"
        assert finance_query == 0, "finance-query is not a seeded skill (dead hardcoded entry)"
    finally:
        await close_pool()


@pytest.mark.asyncio
async def test_min_role_gate_enforced_by_rank(fresh_db, db_settings):
    pool = await apply_migrations(fresh_db, db_settings)
    try:
        async with pool.acquire() as conn:
            member = await conn.fetchval(
                "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
                "VALUES ('m@t', 'x', 'M', 'member') RETURNING id")
            admin = await conn.fetchval(
                "INSERT INTO public.bh_users (email, password_hash, display_name, role) "
                "VALUES ('a@t', 'x', 'A', 'admin') RETURNING id")

        ex = SkillExecutor(Config())
        admin_skill = {"min_role": "admin"}
        open_skill = {"min_role": None}

        # admin-gated: member denied, admin allowed.
        assert await ex._user_meets_min_role(admin_skill, member) is False
        assert await ex._user_meets_min_role(admin_skill, admin) is True
        # no restriction: everyone allowed.
        assert await ex._user_meets_min_role(open_skill, member) is True
        # unknown required role fails closed (member can't satisfy it).
        assert await ex._user_meets_min_role({"min_role": "superuser"}, admin) is False
    finally:
        await close_pool()


def test_role_rank_orders_member_below_admin():
    assert ROLE_RANK["admin"] > ROLE_RANK["member"]
