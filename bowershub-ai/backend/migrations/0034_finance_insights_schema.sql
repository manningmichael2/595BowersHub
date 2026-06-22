-- 0034 — Finance insights schema (proactive nightly insight agent).
--
-- Additive, migrator-owned DDL for .kiro/specs/ai-finance-insights Phase 1
-- (R2.1, R2.4, R2.7, R2.8). Three tables:
--   finance.insights      — the surfaced insights, deduped per (type, merchant, period)
--   finance.insight_runs  — one row per nightly run (R2.8 observability)
--   finance.job_runs      — readiness watermark; the categorizer writes a
--                           'completed' row so the insight runner can gate on
--                           "data is categorized for this window" (R2.1)
--
-- Status columns are text + CHECK (this codebase uses no Postgres ENUMs — they
-- are painful under forward-only migrations). All tables explicitly GRANT SELECT
-- to finance_reader so ask_db / Q&A can read insights (local tests create tables
-- as the superuser, so the migrator default-privilege auto-grant does not fire —
-- the explicit GRANT is required, not redundant).
--
-- Refs: .kiro/specs/ai-finance-insights/{requirements,design}.md (R2.*).

-- 1. The surfaced insights. Deduped on (insight_type, merchant_key, period) so a
--    nightly re-run upserts rather than duplicates (R2.4/R2.7). merchant_key is
--    NOT NULL: it holds the grouping key (a merchant_key, or the account id for
--    account-scoped insights like low-balance-before-payday) so the UNIQUE is
--    meaningful (NULLs would defeat it).
CREATE TABLE IF NOT EXISTS finance.insights (
    id            bigserial PRIMARY KEY,
    insight_type  text NOT NULL,
    merchant_key  text NOT NULL,
    period        text NOT NULL,                         -- YYYY-MM of the triggering activity
    status        text NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'dismissed', 'actioned')),
    dollar_impact numeric(12,2) NOT NULL DEFAULT 0,      -- ranking key (R2.4)
    figures       jsonb NOT NULL DEFAULT '{}'::jsonb,    -- the computed numbers behind it
    reason        text,                                  -- human-readable explanation
    cooldown_until timestamptz,                          -- suppress re-raise until (un-actioned)
    dismissed_at  timestamptz,
    actioned_at   timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    updated_at    timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT insights_type_merchant_period_uniq UNIQUE (insight_type, merchant_key, period)
);
-- Ranking + listing: active insights, biggest dollar-impact first (R2.4).
CREATE INDEX IF NOT EXISTS insights_status_impact_idx
    ON finance.insights (status, dollar_impact DESC);

-- 2. One row per nightly run for observability (R2.8). status records WHY a run
--    did nothing (skipped-not-ready / skipped-disabled) so a silent no-op is
--    distinguishable from a real "nothing detected".
CREATE TABLE IF NOT EXISTS finance.insight_runs (
    id            bigserial PRIMARY KEY,
    started_at    timestamptz NOT NULL DEFAULT now(),
    finished_at   timestamptz,
    status        text NOT NULL
                      CHECK (status IN ('ran', 'skipped-not-ready', 'skipped-disabled', 'errored')),
    detected      integer NOT NULL DEFAULT 0,
    suppressed    jsonb NOT NULL DEFAULT '{}'::jsonb,    -- count by suppression reason
    error         text
);
CREATE INDEX IF NOT EXISTS insight_runs_started_idx ON finance.insight_runs (started_at DESC);

-- 3. Readiness watermark (R2.1). A finance job writes a 'completed' row when it
--    finishes a window; the insight runner gates on the categorizer's row for
--    the target window before running (else the insights would reflect stale,
--    un-categorized data). ran_for is the data date the job processed.
CREATE TABLE IF NOT EXISTS finance.job_runs (
    id           bigserial PRIMARY KEY,
    job_name     text NOT NULL,
    status       text NOT NULL CHECK (status IN ('completed', 'failed', 'running')),
    ran_for      date,
    completed_at timestamptz,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS job_runs_name_completed_idx
    ON finance.job_runs (job_name, completed_at DESC);

-- Explicit least-privilege read grants (R2.4 — Q&A can answer "what insights do
-- I have"). The runner writes via the app/migrator role, never finance_reader.
GRANT SELECT ON finance.insights, finance.insight_runs, finance.job_runs TO finance_reader;
