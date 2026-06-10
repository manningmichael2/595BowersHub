-- 0003_scoped_db_roles.sql — per-app scoped DB roles (C7).
--
-- Goal: stop every service connecting to Postgres as the cluster superuser
-- `michael`, so a compromise of any one service can't read/drop everything.
--
-- This migration CREATES the scoped roles and grants their privileges, but the
-- roles are NOLOGIN — so this is INERT until the deploy cutover (which sets
-- passwords + LOGIN, reassigns object ownership, and switches each service's
-- DB_USER). See docs/c7-db-roles-cutover.md. Idempotent.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bowershub_app') THEN
        -- Runtime role for the main app: powerful WITHIN this database, but not
        -- a cluster superuser. CREATEROLE lets it run role migrations (e.g. 0002).
        CREATE ROLE bowershub_app NOLOGIN NOSUPERUSER CREATEROLE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dashboard_reader') THEN
        CREATE ROLE dashboard_reader NOLOGIN NOSUPERUSER;
    END IF;
END $$;

-- === bowershub_app: main application runtime role ==========================
-- Read/write on all app data, create objects, and SET ROLE finance_reader for
-- ask-db. Not superuser: no pg_read_file / COPY PROGRAM / other databases.
-- Ownership of existing objects is transferred at cutover (REASSIGN OWNED).
GRANT finance_reader TO bowershub_app;

GRANT USAGE, CREATE ON SCHEMA public, finance, inventory, house, cook, files
    TO bowershub_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA
    public, finance, inventory, house, cook, files TO bowershub_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA
    public, finance, inventory, house, cook, files TO bowershub_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA public, finance, inventory, house, cook, files
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bowershub_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public, finance, inventory, house, cook, files
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO bowershub_app;

-- Keep finance_reader able to read future domain tables that bowershub_app
-- creates after the cutover (so ask-db keeps working).
ALTER DEFAULT PRIVILEGES FOR ROLE bowershub_app
    IN SCHEMA finance, inventory, house, cook, files
    GRANT SELECT ON TABLES TO finance_reader;

-- === dashboard_reader: the dashboard service (read-only, narrow) ===========
-- The dashboard only renders API spend from public.api_usage_log.
GRANT USAGE ON SCHEMA public TO dashboard_reader;
GRANT SELECT ON public.api_usage_log TO dashboard_reader;
