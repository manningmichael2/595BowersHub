-- 0002_finance_reader_lockdown.sql — least-privilege role for ask-db (C1/C7).
--
-- ask-db executes LLM-generated SQL. It must run as a role that can read ONLY
-- the domain data (finance/inventory/house/cook/files) and nothing else — in
-- particular NOT the bh_* auth/user tables. The code de-escalates to this role
-- via `SET LOCAL ROLE finance_reader` inside a read-only transaction.
--
-- This migration both creates the role on a fresh database and *fixes* the live
-- role, which had drifted to an over-broad `GRANT SELECT ON ALL TABLES IN
-- SCHEMA public` (it could read public.bh_users — password hashes — and every
-- other bh_* table). Idempotent and safe to re-run.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_reader') THEN
        -- NOLOGIN: never connected to directly; only reached via SET ROLE.
        CREATE ROLE finance_reader NOLOGIN NOSUPERUSER;
    END IF;
END $$;

-- 1. Strip ALL existing access first, so we start from zero and the result is
--    exactly what we re-grant below (removes the over-broad public grants).
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM finance_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM finance_reader;
REVOKE ALL ON SCHEMA public FROM finance_reader;

-- 2. Grant read-only access to ONLY the domain schemas ask-db should reach.
GRANT USAGE ON SCHEMA finance, inventory, house, cook, files TO finance_reader;
GRANT SELECT ON ALL TABLES IN SCHEMA finance, inventory, house, cook, files TO finance_reader;

-- 3. Future tables in those schemas are readable too (no manual re-grant).
ALTER DEFAULT PRIVILEGES IN SCHEMA finance, inventory, house, cook, files
    GRANT SELECT ON TABLES TO finance_reader;
