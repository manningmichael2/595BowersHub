-- 0041 — per-user feature access (R5.2/R5.3 — enforced, restrict-only).
--
-- An admin can DISABLE a feature for a specific user. The resolver treats any
-- enabled=false row as a subtraction and IGNORES enabled=true (an override can
-- never grant above role/floor — restrict-only, D8). A dedicated table (not
-- settings_json): this is admin-set, security-load-bearing, cross-user data that
-- needs an FK + a set_by stamp; keeping it out of the user's own cosmetic prefs
-- is itself a correctness guard.

CREATE TABLE IF NOT EXISTS public.bh_user_feature_access (
    user_id     integer NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    feature_key text    NOT NULL REFERENCES public.bh_features(feature_key) ON DELETE CASCADE,
    enabled     boolean NOT NULL,          -- only enabled=false is meaningful (restrict-only)
    set_by      integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
    set_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, feature_key)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.bh_user_feature_access TO bowershub_app;
