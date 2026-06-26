-- 0039 — capability registry (generalizes 0028's per-skill min_role to
-- endpoint capabilities). The single source of truth for "what role does this
-- gate require"; retuning a gate is an UPDATE here + authz.reload(), never a
-- code change (NO-HARDCODING). Copies bh_skills.min_role semantics so the
-- loader/fail-closed logic is reused, not reinvented (design §Data Model).
--
-- A new table (not a column on bh_skills): capabilities are endpoint gates, a
-- different noun from skills. Recognized roles, lowest->highest: viewer < member
-- < admin (matches bh_users.role + services/authz.py ROLE_RANK).

CREATE TABLE IF NOT EXISTS public.bh_capabilities (
    capability text PRIMARY KEY,
    min_role   text NOT NULL CHECK (min_role IN ('viewer', 'member', 'admin')),
    description text,
    updated_at timestamptz NOT NULL DEFAULT now(),
    updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL
);

-- Seed the enumerated capabilities. Kept in lockstep with authz._DEFAULT_CAPS
-- (a test asserts the two are equal). Idempotent: existing rows keep any admin
-- retune already applied.
INSERT INTO public.bh_capabilities (capability, min_role, description) VALUES
  ('finance.read',           'viewer', 'View finance data'),
  ('finance.write',          'member', 'Everyday finance writes (categorize/split/budget/rules/retirement) — D2'),
  ('finance.insight.action', 'member', 'Dismiss/action insights — resolves D2 vs require_admin'),
  ('finance.delete',         'admin',  'Structural/destructive finance ops (delete/account-type) — D2'),
  ('users.manage',           'admin',  'User provisioning & role changes'),
  ('settings.write',         'admin',  'Platform/theme/skill/model/hooks settings'),
  ('db.query',               'admin',  'ask-db / finance-query skills'),
  ('db.browser',             'admin',  'DB browser — admin-only floor')
ON CONFLICT (capability) DO NOTHING;

-- Runtime reads the registry; only migrations/admin edits write it.
GRANT SELECT ON public.bh_capabilities TO bowershub_app;
