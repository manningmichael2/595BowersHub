-- 0004_n8n_scoped_role.sql — scoped DB role for n8n (C7 follow-up).
--
-- Closes the last superuser app connection: n8n's "Finance Postgres" credential
-- connected as the cluster superuser `michael`. n8n runs automation workflows —
-- several with dynamic (`{{ $json.sql }}`) Postgres nodes — so a superuser
-- credential there means any workflow (or a compromise of n8n) could read
-- password hashes (public.bh_users) or run server-side programs.
--
-- This creates `n8n_app`: NOSUPERUSER, NOCREATEROLE, read/write on the *data*
-- schemas + the public compat views the workflows use, but NO access to the
-- auth/secrets tables (public.bh_users, bh_refresh_tokens, ...) and no DDL.
--
-- Like 0003, the role is created NOLOGIN — INERT until the deploy cutover sets a
-- password + LOGIN and switches the n8n credential. See docs/c7-n8n-role-cutover.md.
-- Runs as `bowershub_app`, which owns these schemas/objects, so every GRANT here
-- is by ownership. Idempotent.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'n8n_app') THEN
        CREATE ROLE n8n_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END $$;

-- === Data schemas: full read/write, no CREATE (no DDL) =====================
-- The finance schema move (021) left updatable compat VIEWS in `public`
-- (public.transactions -> finance.transactions, ...) that the workflows target;
-- those views are owned by bowershub_app, so view-mediated writes are checked
-- against the owner. We ALSO grant DML directly on the base tables so the
-- workflows that reference data schemas directly (files.assets) and the
-- dynamic-SQL nodes keep working.
GRANT USAGE ON SCHEMA finance, inventory, house, cook, files TO n8n_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA
    finance, inventory, house, cook, files TO n8n_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA
    finance, inventory, house, cook, files TO n8n_app;

-- Future tables/sequences created by bowershub_app in the data schemas inherit
-- the same grants (no manual re-grant when the app adds a table).
ALTER DEFAULT PRIVILEGES IN SCHEMA finance, inventory, house, cook, files
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA finance, inventory, house, cook, files
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO n8n_app;

-- === public: ONLY the compat views + api_usage_log, never the bh_*/auth tables.
-- USAGE on schema public comes from the PUBLIC default. We deliberately do NOT
-- grant on ALL TABLES IN public (that holds bh_users password hashes, refresh
-- tokens, etc.). New public objects are NOT auto-granted — auth lives here, so
-- exposure must always be explicit.
GRANT SELECT, INSERT, UPDATE, DELETE ON
    public.accounts,
    public.alert_log,
    public.budgets,
    public.categories,
    public.category_examples,
    public.email_classified,
    public.email_labels,
    public.transaction_files,
    public.transactions,
    public.api_usage_log
    TO n8n_app;

-- api_usage_log is a real public table (not a compat view), so its INSERTs need
-- nextval on the backing sequence. The compat views write into finance.* whose
-- sequences are already granted above; this is the only public sequence needed.
GRANT USAGE, SELECT ON SEQUENCE public.api_usage_log_id_seq TO n8n_app;

-- Belt-and-suspenders: make the intent explicit and defeat any inherited PUBLIC
-- grant on the secrets tables. (n8n_app was never granted these; REVOKE is a
-- no-op today but documents the boundary and is safe to re-run.)
REVOKE ALL ON public.bh_users, public.bh_refresh_tokens,
    public.bh_password_reset_tokens, public.bh_invite_links FROM n8n_app;
