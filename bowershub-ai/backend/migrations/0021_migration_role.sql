-- 0021_migration_role.sql — dedicated migration role (project-review.md C1/C7).
--
-- Why: the 2026-06-19 deploy crash-looped because schema migrations ran as the
-- least-privilege runtime role `bowershub_app`, which does NOT own the legacy
-- postgres-owned objects (public.transactions view, finance.transactions) and
-- cannot CREATE EXTENSION. Migration 0016's `DROP/CREATE VIEW` failed with
-- "must be owner of view transactions". The fix (Option 1) splits privilege:
--   • runtime  → bowershub_app   (scoped, DB_USER)            — least privilege
--   • migrate  → bowershub_migrator (elevated, MIGRATION_DB_USER) — DDL
-- run_migrations() opens a short-lived connection as the migration role; the
-- request-handling pool never holds those creds. See docs/c7-db-roles-cutover.md.
--
-- This migration is the version-controlled, from-scratch-reproducible half:
-- it ensures the role exists and—critically—wires the DEFAULT PRIVILEGES so that
-- objects the migration role creates are reachable by the runtime roles. The
-- privileged half (password + LOGIN + SUPERUSER) is a one-time manual cutover
-- step run as the cluster superuser — secrets and superuser escalation never
-- live in a VCS-tracked migration. Idempotent.
--
-- Background: every prior ALTER DEFAULT PRIVILEGES (0002/0003/0004) is keyed to
-- the *creating* role bowershub_app. Once migrations create objects as
-- bowershub_migrator instead, NONE of those defaults fire, so new tables would
-- silently lose the grants the app / n8n / ask-db rely on. We therefore mirror
-- all of them FOR ROLE bowershub_migrator below.

DO $$
BEGIN
    -- NOLOGIN/NOSUPERUSER here: inert until the manual cutover grants LOGIN +
    -- SUPERUSER + a password. On a from-scratch test/CI rebuild this role is
    -- created but unused (those suites connect as the superuser DB_USER), which
    -- keeps the schema buildable from empty without needing the cutover.
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'bowershub_migrator') THEN
        CREATE ROLE bowershub_migrator NOLOGIN NOSUPERUSER;
    END IF;
END $$;

-- The migration role must be able to create objects in the app schemas (so
-- from-scratch rebuilds run as this role work) and SET ROLE into the runtime
-- role if ever needed. Schemas exist by now (created in the 0001 baseline).
GRANT USAGE, CREATE ON SCHEMA public, finance, inventory, house, cook, files
    TO bowershub_migrator;

-- === Default privileges for objects CREATED BY bowershub_migrator ==========
-- Mirror of 0003 (bowershub_app runtime) — DML + sequence access on everything.
ALTER DEFAULT PRIVILEGES FOR ROLE bowershub_migrator
    IN SCHEMA public, finance, inventory, house, cook, files
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO bowershub_app;
ALTER DEFAULT PRIVILEGES FOR ROLE bowershub_migrator
    IN SCHEMA public, finance, inventory, house, cook, files
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO bowershub_app;

-- Mirror of 0002/0003 (finance_reader / ask-db) — SELECT on the domain schemas
-- only; never public (auth + secrets live there).
ALTER DEFAULT PRIVILEGES FOR ROLE bowershub_migrator
    IN SCHEMA finance, inventory, house, cook, files
    GRANT SELECT ON TABLES TO finance_reader;

-- Mirror of 0004 (n8n_app) — DML + sequence access on the domain schemas only.
-- Deliberately NOT public: 0004 grants n8n only specific public tables, never
-- the bh_*/auth tables, so future public objects must not auto-grant to n8n.
ALTER DEFAULT PRIVILEGES FOR ROLE bowershub_migrator
    IN SCHEMA finance, inventory, house, cook, files
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO n8n_app;
ALTER DEFAULT PRIVILEGES FOR ROLE bowershub_migrator
    IN SCHEMA finance, inventory, house, cook, files
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO n8n_app;
