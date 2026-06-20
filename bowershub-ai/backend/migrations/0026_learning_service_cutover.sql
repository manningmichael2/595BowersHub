-- 0026 — Learning cutover (R3, §10-T2): drop the 0018 trigger + forward-migrate
-- category_examples into merchant_memory.
--
-- Owned-object DDL (DROP TRIGGER/FUNCTION on finance.transactions) → authored for
-- the bowershub_migrator role (C7 cutover live). Applies cleanly from empty (C2):
-- on fresh_db category_examples is empty so the data copy is a no-op; the
-- trigger/function drops are IF EXISTS.
--
-- The deterministic LearningService (services/categorization/learning.py) now
-- owns reinforcement: it computes the normalized merchant_key in Python (which a
-- SQL trigger could not do without re-implementing the rules) and writes
-- finance.merchant_memory + a provenance row. The 0018 first-alphabetic-word
-- trigger is therefore retired.
--
-- KEPT untouched (critic M1): finance.category_aliases + lookup_category_alias —
-- a different map (NL category *name* → id), unrelated to merchant keys. Only the
-- trigger + its function are dropped here. The category_examples TABLE and its
-- public view are left in place (deprecated) so this migration stays reversible
-- and non-destructive; the active writer is redirected in code (B-1).
--
-- DOWN-MIGRATION (manual, documented): re-create fn_learn_from_manual_override +
-- trg_learn_from_manual_override from 0018. merchant_memory rows seeded here are
-- additive and harmless to leave; to fully revert, TRUNCATE the rows whose
-- provenance source = 'category_examples_migration'.
--
-- Refs: .kiro/specs/finance-categorization (Task 7; R3.1, R3.2).

-- 1. Forward-migrate the learned signal. category_examples.description_pattern is
--    already an UPPER token/pattern, so UPPER(trim()) approximates the normalized
--    merchant_key for the common single-merchant case (exact for single tokens
--    like COSTCO; LearningService keys correctly from here forward). ON CONFLICT
--    DO NOTHING keeps it idempotent (no double-counting on re-apply).
INSERT INTO finance.merchant_memory (merchant_key, category_id, times_reinforced, last_reinforced_at)
SELECT UPPER(trim(description_pattern)), category_id, times_reinforced, COALESCE(updated_at, now())
FROM finance.category_examples
WHERE description_pattern IS NOT NULL AND trim(description_pattern) <> ''
ON CONFLICT (merchant_key, category_id) DO NOTHING;

-- Provenance for the forward-migration (one row marking the cutover).
INSERT INTO finance.categorization_decision (transaction_id, tier, applied_category_id, auto_applied, rationale)
SELECT 'migration:0026', 'correction', NULL, false,
       jsonb_build_object('source', 'category_examples_migration',
                          'rows', (SELECT count(*) FROM finance.category_examples))
WHERE EXISTS (SELECT 1 FROM finance.category_examples);

-- 2. Drop the 0018 learning trigger + function (the only objects retired).
DROP TRIGGER IF EXISTS trg_learn_from_manual_override ON finance.transactions;
DROP FUNCTION IF EXISTS finance.fn_learn_from_manual_override();
