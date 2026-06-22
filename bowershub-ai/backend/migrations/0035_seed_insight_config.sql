-- 0035 — Insight detector config (DB-driven thresholds + kill-switch).
--
-- NO-HARDCODING (Rule #1): every detector enable flag, threshold, the global
-- kill-switch, and the retirement-intent keyword set are rows in
-- finance.insight_config (key text → jsonb value), read by
-- services/finance_insights/config.py. Code holds these values ONLY as a
-- missing-key fallback. Seeds are idempotent (ON CONFLICT DO NOTHING) so
-- re-applying never clobbers an operator's tuned value.
--
-- Refs: .kiro/specs/ai-finance-insights/{requirements,design}.md (R2.2).

CREATE TABLE IF NOT EXISTS finance.insight_config (
    key        text PRIMARY KEY,
    value      jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO finance.insight_config (key, value) VALUES
    -- Global kill-switch (R2 — a single row disables the whole nightly agent).
    ('insights_enabled',                          'true'::jsonb),

    -- duplicate-charge: same merchant + (near-)equal amount within N days.
    ('detector.duplicate_charge.enabled',         'true'::jsonb),
    ('detector.duplicate_charge.window_days',     '3'::jsonb),
    ('detector.duplicate_charge.amount_tolerance','0.00'::jsonb),

    -- price-creep: a recurring charge's amount rises vs its history.
    ('detector.price_creep.enabled',              'true'::jsonb),
    ('detector.price_creep.min_increase_pct',     '0.15'::jsonb),
    ('detector.price_creep.min_history',          '3'::jsonb),

    -- free-trial-conversion: a new recurring charge after a trial/$0 period.
    ('detector.free_trial_conversion.enabled',    'true'::jsonb),
    ('detector.free_trial_conversion.min_amount', '5.00'::jsonb),
    ('detector.free_trial_conversion.lookback_days','45'::jsonb),

    -- unusual-spend: a category's monthly total deviates (median/MAD).
    ('detector.unusual_spend.enabled',            'true'::jsonb),
    ('detector.unusual_spend.mad_multiplier',     '3.0'::jsonb),
    ('detector.unusual_spend.min_history',        '6'::jsonb),

    -- bill-higher-than-usual: a recurring bill above its IQR fence.
    ('detector.bill_higher_than_usual.enabled',   'true'::jsonb),
    ('detector.bill_higher_than_usual.iqr_multiplier','1.5'::jsonb),
    ('detector.bill_higher_than_usual.min_history','4'::jsonb),

    -- low-balance-before-payday: projected balance below a floor near payday.
    ('detector.low_balance_before_payday.enabled','true'::jsonb),
    ('detector.low_balance_before_payday.floor',  '100.00'::jsonb),

    -- Retirement-intent keyword set for the Q&A classifier (Task 17, R4.5) — a
    -- config row, not a hardcoded list.
    ('retirement_keywords',
     '["retire","retirement","fire","nest egg","withdraw","withdrawal","coast","pension","401k","ira","roth","social security"]'::jsonb)
ON CONFLICT (key) DO NOTHING;
