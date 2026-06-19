-- Migration 0020: Tighten the L1 "merchant is category" deterministic pattern.
--
-- The 0019 rule `^(\w+) is (\w+)$` fires on ANY two-word "X is Y" sentence
-- ("Today is Monday", "what is balance") and bypasses the LLM router entirely,
-- producing confusing "Category 'Monday' not found" replies. We restrict L1 to
-- high-confidence categorization phrasing ("X is always Y", "X should be Y") and
-- let casual "X is Y" fall through to the L2 router (which has examples and is
-- context-aware). The merchant side now also allows multi-word names.
UPDATE public.bh_patterns
SET rule = '(?i)^(.+?)\s+(?:is\s+always|should\s+be|should\s+always\s+be)\s+([A-Za-z][A-Za-z_ ]*?)$'
WHERE description = 'Deterministic "Merchant is Category" rule';

-- Deterministic route for the /transactions interactive links, which pre-fill
-- the composer with "Recategorize <txn-id> to <category>". Guarantees the click
-- works without depending on LLM classification.
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority, is_active)
SELECT
    '(?i)^recategorize\s+(\S+)\s+to\s+(.+)$',
    'regex',
    s.id,
    '{"transaction_id": "$1", "category_name": "$2"}',
    'Deterministic "Recategorize <id> to <category>" rule',
    50,
    true
FROM public.bh_skills s
WHERE s.name = 'categorize-transaction'
  AND NOT EXISTS (
    SELECT 1 FROM public.bh_patterns p
    WHERE p.description = 'Deterministic "Recategorize <id> to <category>" rule'
  );
