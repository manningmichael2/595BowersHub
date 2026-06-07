-- ============================================================================
-- 008 — DB Admin field hints table
-- ============================================================================
-- Stores per-column-name input configuration for the DB Admin form system.
-- Replaces the hardcoded FIELD_HINTS in app.js with a user-editable config.
-- Column names are global (same name = same widget everywhere).
--
-- Idempotent: safe to run multiple times.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.db_admin_field_hints (
    column_name     TEXT PRIMARY KEY,           -- e.g. 'condition', 'purchase_price', 'motor_amps'
    hint_type       TEXT NOT NULL DEFAULT 'text', -- text|number|fraction|select|url|date|boolean
    options         JSONB,                      -- for select: ["new","good","fair",...] 
    prefix          TEXT,                       -- e.g. '$'
    suffix          TEXT,                       -- e.g. '"', '°', 'lbs'
    min_val         NUMERIC,                    -- for number type
    max_val         NUMERIC,                    -- for number type
    step_val        NUMERIC,                    -- for number type
    placeholder     TEXT,                       -- input placeholder text
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Grant read access to finance_reader if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_reader') THEN
        EXECUTE 'GRANT SELECT ON public.db_admin_field_hints TO finance_reader';
    END IF;
END $$;

COMMENT ON TABLE public.db_admin_field_hints IS 'Per-column input type configuration for DB Admin forms. Overrides hardcoded FIELD_HINTS defaults.';
