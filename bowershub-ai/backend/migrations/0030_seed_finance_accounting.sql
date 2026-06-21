-- 0030 — Seed finance-accounting config + correct existing account metadata.
--
-- DML, idempotent, guarded. NOTE: finance.accounts rows come from the SimpleFin
-- sync, not migrations — so the account UPDATEs below are a no-op on a fresh DB
-- (no rows yet) and a one-time correction on prod. account_type for accounts
-- created by future syncs is operational metadata, set via the admin set-type API
-- (net-worth flags untyped accounts as "needs type", R3.1) — there is no static
-- seed that can reproduce it. Dry-run (BEGIN…ROLLBACK) against the populated prod
-- DB before deploy (0023-incident lesson).
--
-- Refs: .kiro/specs/finance-accounting (R3.3, R4.1, R4.3).

-- 1. Type the still-untyped Rocket Mortgage account (the ~-160k liability) so it
--    classifies as a liability in net worth (R4.1). Guarded: only NULL types.
UPDATE finance.accounts
SET account_type = 'mortgage'
WHERE org_name = 'Rocket Mortgage' AND account_type IS NULL;

-- 2. Exclude non-spending/synthetic orgs from net worth (R3.3) — replaces the
--    former hardcoded list in dashboard.py. Guarded so re-runs are no-ops.
UPDATE finance.accounts
SET include_in_net_worth = false
WHERE org_name IN ('Email Receipts', 'ADP Redbox', 'Credit Karma')
  AND include_in_net_worth = true;

-- 3. Accounting config defaults (R4.3). DB-driven tunables, never code constants.
INSERT INTO finance.accounting_config (key, value)
SELECT k, v::jsonb FROM (VALUES
    ('match_date_window_days', '4'),
    ('match_amount_tolerance', '0.01'),
    ('reconcile_tolerance',    '0.01'),
    ('stale_balance_days',     '7')
) AS d(k, v)
WHERE NOT EXISTS (SELECT 1 FROM finance.accounting_config c WHERE c.key = d.k);
