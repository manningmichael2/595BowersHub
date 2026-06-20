-- 0024 — Seed the default merchant-normalization rules (R1.1/R1.4).
--
-- DML; the engine in services/merchant_normalizer.py applies these as ordered
-- regex substitutions to the raw bank descriptor, then collapses whitespace and
-- title-cases. NO-HARDCODING: the rules are data, so the long tail is tuned by
-- adding rows, not editing code. Guarded so it only seeds an empty table (a
-- genuine no-op if rules already exist). standard_conforming_strings is on, so
-- the backslashes below are stored literally (what Python `re` expects).
--
-- Refs: .kiro/specs/finance-categorization (Task 3; R1.1, R1.4).

INSERT INTO finance.normalization_rules (rule_type, pattern, replacement, priority)
SELECT v.rule_type, v.pattern, v.replacement, v.priority
FROM (VALUES
    -- Strip leading payment-intermediary prefixes (Square/Toast/PayPal/Stripe...).
    -- The trailing `\*` requirement avoids eating real names like SPOTIFY / PPG.
    ('strip_intermediary',    '^\s*(SQ|TST|PYPL|PP|SP|PAYPAL)\s*\*\s*', '', 10),
    -- Strip a store/location number and everything after it (drops trailing city/state junk).
    ('strip_store_number',    '\s*#\s*\d+.*$',                          '', 20),
    -- Strip a store-type keyword and everything after it.
    ('strip_store_type',      '\s+(WHSE|SUPERCENTER|SUPER CENTER|MKTP|MARKETPLACE|STORE)\b.*$', '', 30),
    -- Strip a trailing bare store number (no '#').
    ('strip_trailing_number', '\s+\d{3,}\s*$',                          '', 40)
) AS v(rule_type, pattern, replacement, priority)
WHERE NOT EXISTS (SELECT 1 FROM finance.normalization_rules);
