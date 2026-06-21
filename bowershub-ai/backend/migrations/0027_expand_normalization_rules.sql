-- 0027 — Expand merchant-normalization rules (R1.1/R1.4 tail).
--
-- The 0024 seed (4 rules) left merchant_key ≈ the full uppercased descriptor for
-- the long tail, so the same merchant fragmented across many keys (e.g. ~30
-- distinct AMAZON MKTPL*<order-code> keys). That starves the merchant-memory and
-- kNN tiers, which key on merchant_key. These rules were derived data-driven
-- against the live descriptors (scripts/normalization_dryrun.py): 209→160 keys,
-- 138→86 singletons, with no wrong merges.
--
-- ORDER MATTERS. The generic trailing-junk strippers (priority 42–48) run before
-- the anchored whole-merchant collapses (50+), which are terminal — so a collapse
-- that emits e.g. "GOOGLE FI" / "YOUTUBE TV" is never re-stripped by the
-- 2-letter-state rule. standard_conforming_strings is on, so backslashes are
-- stored literally (what Python `re` expects). Each row is guarded by pattern so
-- re-applying is a true no-op (0023 incident lesson).
--
-- Refs: .kiro/specs/finance-categorization (R1.1, R1.4).

INSERT INTO finance.normalization_rules (rule_type, pattern, replacement, priority)
SELECT v.rule_type, v.pattern, v.replacement, v.priority
FROM (VALUES
    -- Generic trailing-junk strippers (run before the collapses).
    ('strip_processor_tail',  '\s*~.*$',                                                   '', 42),
    ('strip_phone',           '\s+1?[-\s]?\(?\d{3}\)?[-\s]?\d{3}[-\s]?\d{4}\b.*$',          '', 44),
    ('strip_state',           '\s+[A-Z]{2}\s*$',                                           '', 46),
    ('strip_trailing_sep',    '[\s\-–—]+$',                                                '', 48),
    -- Whole-merchant collapses (anchored, terminal) — fold fragmented merchants.
    ('collapse_merchant',     '^AMAZON\b.*$',                                       'AMAZON', 50),
    ('collapse_merchant',     '^GOOGLE\s*\*?\s*YOUTUBE TV.*$',                  'YOUTUBE TV', 51),
    ('collapse_merchant',     '^GOOGLE\s*\*?\s*GOOGLE ONE.*$',                  'GOOGLE ONE', 52),
    ('collapse_merchant',     '^GOOGLE\s*\*?\s*FI\b.*$',                         'GOOGLE FI', 53),
    ('collapse_merchant',     '^WHOLE\s?F(OO)?DS\b.*$',                        'WHOLE FOODS', 54),
    ('collapse_merchant',     '^WAL-?MART\s*\+?\s*MEMBER.*$',              'WALMART+ MEMBER', 55),
    -- Interest INCOME variants only — must NOT fold "Interest Charge on Purchases"
    -- (a credit-card interest expense) in with interest earned.
    ('collapse_merchant',     '^INTEREST(\s+(PAID|INCOME|PAYMENT|FOR)\b.*)?$',    'INTEREST', 56),
    ('collapse_merchant',     '^INVESTMENT ADMIN FEE.*$',             'INVESTMENT ADMIN FEE', 57),
    ('collapse_merchant',     '^INTERNET TRANSFER\b.*$',                 'INTERNET TRANSFER', 58)
) AS v(rule_type, pattern, replacement, priority)
WHERE NOT EXISTS (
    SELECT 1 FROM finance.normalization_rules r WHERE r.pattern = v.pattern
);
