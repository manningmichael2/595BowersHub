-- 0032 — Seed budget alert-threshold config (R3.5, R4.2).
--
-- DML, idempotent, guarded. Moves the hardcoded 80%/100% budget-alert thresholds
-- out of services/alerts.py into DB-driven config (NO-HARDCODING). Reuses the
-- finance.accounting_config k/v table from 0029. No-op on re-run.
--
-- finance.categories.budget_monthly is hereby DEPRECATED (unread) — finance.budgets
-- is the single budget store (R3.1). No DDL change; documented here.
--
-- Refs: .kiro/specs/finance-budgets-splits (R3.1, R3.5, R4.2).

INSERT INTO finance.accounting_config (key, value)
SELECT k, v::jsonb FROM (VALUES
    ('budget_warn_ratio', '0.8'),
    ('budget_over_ratio', '1.0')
) AS d(k, v)
WHERE NOT EXISTS (SELECT 1 FROM finance.accounting_config c WHERE c.key = d.k);
