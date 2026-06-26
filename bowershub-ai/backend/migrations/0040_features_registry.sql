-- 0040 — feature registry (R5.1). A "feature" is a user-facing area (Finance,
-- Database) with nav routes + a baseline capability + an optional admin-only
-- floor. NO-HARDCODING: adding/retuning a feature is a row, not a code constant.
--
-- baseline_capability FKs the capability registry (0039) so a feature always
-- points at a real gate; the boot self-check additionally validates it resolves
-- (catches a typo the FK alone wouldn't, since 0039 may not have that row yet
-- at seed time — belt and suspenders).
--
-- admin_only_floor=true (database) means: never grantable below admin, even by a
-- per-user override (the floor is applied unconditionally in authz.resolve — Task 9).

CREATE TABLE IF NOT EXISTS public.bh_features (
    feature_key         text PRIMARY KEY,                              -- 'finance','database'
    label               text NOT NULL,
    nav_routes          jsonb NOT NULL DEFAULT '[]',
    baseline_capability text REFERENCES public.bh_capabilities(capability),
    admin_only_floor    boolean NOT NULL DEFAULT false
);

INSERT INTO public.bh_features (feature_key, label, nav_routes, baseline_capability, admin_only_floor) VALUES
  ('finance',  'Finance',  '["/finance"]',  'finance.read', false),
  ('database', 'Database', '["/database"]', 'db.browser',   true)
ON CONFLICT (feature_key) DO NOTHING;

GRANT SELECT ON public.bh_features TO bowershub_app;
