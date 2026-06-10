-- Migration 022: DB Browser Views — per-user per-table saved view configurations
--
-- Stores named filter/sort/column-visibility presets for the native DB browser.
-- Each view captures a combination of filter conditions, sort order, and column
-- visibility as a JSONB payload, scoped per user and per table.
--
-- Requirements: 28.4, 28.6
--   - API endpoints for reading and creating per-user per-table view configurations
--   - Views stored in bh_db_browser_views, scoped per user and per table

CREATE TABLE IF NOT EXISTS public.bh_db_browser_views (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    schema_name TEXT NOT NULL,
    table_name  TEXT NOT NULL,
    name        TEXT NOT NULL,
    config      JSONB NOT NULL DEFAULT '{}',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_db_browser_views_user_schema_table
    ON public.bh_db_browser_views (user_id, schema_name, table_name);
