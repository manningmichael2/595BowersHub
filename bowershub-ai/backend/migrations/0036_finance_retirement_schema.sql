-- 0036 — Retirement planner schema (.kiro/specs/ai-finance-insights Phase 3).
--
-- finance.retirement_inputs is a SINGLETON (one owner): id fixed to 1 via a
-- DEFAULT + CHECK so a second row can't be inserted. It holds every user-entered
-- field (the projection is reactive to these) PLUS nullable per-user overrides of
-- the assumptions — NULL means "fall back to finance.retirement_config" (0037).
-- finance.retirement_scenarios holds many saved what-if scenarios for compare
-- (R4.4). Both are GRANTed SELECT to finance_reader so ask_db/Q&A can read them.
--
-- Refs: requirements R4.1, R4.3, R4.4, R4.8.

CREATE TABLE IF NOT EXISTS finance.retirement_inputs (
    id                  integer PRIMARY KEY DEFAULT 1 CHECK (id = 1),  -- singleton
    current_age         integer,
    retirement_age      integer,
    current_balance     numeric(14,2),
    annual_salary       numeric(14,2),
    annual_contribution numeric(14,2),
    annual_expenses     numeric(14,2),
    -- Per-user assumption overrides (NULL → retirement_config default).
    expected_return     numeric(6,4),
    inflation_rate      numeric(6,4),
    withdrawal_rate     numeric(6,4),
    end_age             integer,
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS finance.retirement_scenarios (
    id         serial PRIMARY KEY,
    name       text NOT NULL,
    overrides  jsonb NOT NULL DEFAULT '{}'::jsonb,   -- input + assumption overrides
    created_at timestamptz NOT NULL DEFAULT now()
);

GRANT SELECT ON finance.retirement_inputs, finance.retirement_scenarios TO finance_reader;
