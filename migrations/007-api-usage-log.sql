-- ============================================================================
-- 007 — API usage logging table
-- ============================================================================
-- Tracks per-call token usage and estimated cost for Anthropic API calls
-- made by n8n workflows. Enables spend analysis by workflow, model, and day.
--
-- Idempotent: safe to run multiple times.
-- ============================================================================

CREATE TABLE IF NOT EXISTS public.api_usage_log (
    id              BIGSERIAL    PRIMARY KEY,
    called_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),
    workflow_id     TEXT,                       -- n8n workflow ID
    workflow_name   TEXT,                       -- human-readable workflow name
    node_name       TEXT,                       -- which node made the call
    model           TEXT         NOT NULL,      -- e.g. 'claude-haiku-4-5-20251001'
    input_tokens    INTEGER      NOT NULL DEFAULT 0,
    output_tokens   INTEGER      NOT NULL DEFAULT 0,
    cache_read_tokens  INTEGER   NOT NULL DEFAULT 0,
    cache_write_tokens INTEGER   NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10,6),             -- estimated cost in USD
    duration_ms     INTEGER,                   -- how long the API call took
    metadata        JSONB                      -- optional extra context
);

CREATE INDEX IF NOT EXISTS api_usage_log_called_at_idx ON public.api_usage_log (called_at DESC);
CREATE INDEX IF NOT EXISTS api_usage_log_workflow_idx  ON public.api_usage_log (workflow_name);
CREATE INDEX IF NOT EXISTS api_usage_log_model_idx    ON public.api_usage_log (model);

-- Grant read access to finance_reader if it exists
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finance_reader') THEN
        EXECUTE 'GRANT SELECT ON public.api_usage_log TO finance_reader';
    END IF;
END $$;

COMMENT ON TABLE public.api_usage_log IS 'Per-call Anthropic API token usage and cost tracking. Populated by n8n workflows after each LLM call.';
