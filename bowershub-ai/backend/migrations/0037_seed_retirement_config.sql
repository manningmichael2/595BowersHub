-- 0037 — Retirement assumption defaults (DB-driven, editable prefill).
--
-- NO-HARDCODING: the projection assumptions are rows in finance.retirement_config
-- (key→jsonb), read by services/retirement.py. These are DEFAULTS only — the
-- planner is reactive to user-entered fields, and retirement_inputs may override
-- any of them per-projection. Idempotent (ON CONFLICT DO NOTHING) so re-applying
-- never clobbers a tuned value.
--
-- Refs: requirements R4.1, R4.3.

CREATE TABLE IF NOT EXISTS finance.retirement_config (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO finance.retirement_config (key, value) VALUES
    ('nominal_return',  '0.07'::jsonb),   -- 7% nominal annual return
    ('inflation',       '0.03'::jsonb),   -- 3% inflation
    ('withdrawal_rate', '0.04'::jsonb),   -- 4% safe-withdrawal rule
    ('end_age',         '95'::jsonb)      -- planning horizon
ON CONFLICT (key) DO NOTHING;
