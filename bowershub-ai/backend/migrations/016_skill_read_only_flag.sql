-- Migration 016: Add is_read_only flag to bh_skills (replaces hardcoded _LOW_RISK_SKILLS)
-- 
-- Context: The L2 classifier uses a lower confidence threshold (0.65) for read-only
-- skills vs write-path skills (0.75). Previously this was a hardcoded Python set.
-- Now it's a DB column that can be managed via admin UI without code changes.
--
-- Also documents the two api_usage_log tables for clarity:
--   public.api_usage_log     → Anthropic API cost tracking (n8n + BowersHub AI)
--   public.bh_api_usage_log  → External HTTP call log from the toolbox
-- These serve different purposes and are intentionally separate.

-- Add the column
ALTER TABLE public.bh_skills
    ADD COLUMN IF NOT EXISTS is_read_only BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.bh_skills.is_read_only IS
    'Read-only/info skills get a lower L2 confidence threshold (0.65 vs 0.75). Set true for skills that only retrieve data and never modify state.';

-- Set existing read-only skills
UPDATE public.bh_skills SET is_read_only = true
WHERE name IN (
    'weather',
    'sports-score',
    'news',
    'get-balances',
    'filter-transactions',
    'spending-summary',
    'ask-db',
    'recall',
    'list-files'
);

-- Document the usage log tables
COMMENT ON TABLE public.bh_api_usage_log IS
    'External HTTP API call log from the universal toolbox. Tracks URL, status code, duration. Used for API usage pattern detection. NOT for Anthropic cost tracking (that is public.api_usage_log).';
