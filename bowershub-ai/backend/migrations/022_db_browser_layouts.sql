-- Migration 022: DB Browser Layouts — per-user per-table layout configuration
--
-- Stores detail view and list view layout preferences (field order, visibility,
-- width, height) for the native DB browser. One row per user+schema+table combo.
--
-- Requirements: 10.5, 24.2
--   - Layout preferences persisted to backend (not localStorage)
--   - Database-driven configuration for the DB browser

CREATE TABLE IF NOT EXISTS public.bh_db_browser_layouts (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    schema_name   TEXT NOT NULL,
    table_name    TEXT NOT NULL,
    list_config   JSONB NOT NULL DEFAULT '{}',
    detail_config JSONB NOT NULL DEFAULT '{}',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, schema_name, table_name)
);

CREATE INDEX IF NOT EXISTS idx_db_browser_layouts_user_id
    ON public.bh_db_browser_layouts (user_id);
