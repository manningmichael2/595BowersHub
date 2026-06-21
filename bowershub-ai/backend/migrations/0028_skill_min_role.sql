-- 0028 — DB-driven per-skill minimum role (replaces the hardcoded
-- ADMIN_ONLY_SKILLS set in services/skill_executor.py).
--
-- NO-HARDCODING: gating a skill to a role is now a data change (a min_role value
-- on the row), not a code constant. NULL = no role restriction (everyone allowed,
-- subject to the existing user/workspace checks). Recognized roles, lowest→highest:
-- 'member' < 'admin' (matches bh_users.role).
--
-- Preserves prior behavior: the old ADMIN_ONLY_SKILLS set listed {ask-db,
-- finance-query}, but only `ask-db` is an actual seeded skill — `finance-query`
-- was a dead/defensive entry (registered nowhere). The guarded UPDATE below
-- gates whichever of those rows exist (today: just ask-db). Idempotent.
--
-- Refs: project-review.md §9 / CLAUDE.md "smaller NO-HARDCODING tail".

ALTER TABLE public.bh_skills ADD COLUMN IF NOT EXISTS min_role text;

UPDATE public.bh_skills
SET min_role = 'admin'
WHERE name IN ('ask-db', 'finance-query') AND min_role IS NULL;
