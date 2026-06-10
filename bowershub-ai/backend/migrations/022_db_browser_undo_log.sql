-- Migration 022: DB Browser Undo Log — session-scoped undo/redo stack
--
-- Stores data operations (edits, inserts, deletes, bulk updates) with their
-- previous and new values so users can undo/redo changes within a browser session.
--
-- Requirements: 29.6
--   - Server-side session-scoped undo log so undone changes persist across
--     page refreshes within the same session

CREATE TABLE IF NOT EXISTS public.bh_db_browser_undo_log (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES public.bh_users(id) ON DELETE CASCADE,
    schema_name     TEXT NOT NULL,
    table_name      TEXT NOT NULL,
    row_id          TEXT NOT NULL,
    operation_type  TEXT NOT NULL CHECK (operation_type IN ('update', 'insert', 'delete', 'bulk_update')),
    previous_values JSONB,
    new_values      JSONB,
    is_undone       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_db_browser_undo_log_session_created
    ON public.bh_db_browser_undo_log (session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_db_browser_undo_log_session_undone
    ON public.bh_db_browser_undo_log (session_id, is_undone);
