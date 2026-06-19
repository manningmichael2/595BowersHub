-- Migration 0019: Lifetime Financial Core - Schema Hardening and Tool Decoupling
-- This migration implements strict integrity constraints and registers the new decoupled tools.

-- 1. Hardening: Prevent "Ghost Rows" (Empty Transactions)
-- First, ensure no current data violates the new constraints (though our audit showed 0 violations)
DELETE FROM finance.transactions WHERE description IS NULL OR TRIM(description) = '' OR amount IS NULL OR posted_date IS NULL;

ALTER TABLE finance.transactions 
    ADD CONSTRAINT transactions_desc_not_empty CHECK (length(TRIM(description)) > 0),
    ADD CONSTRAINT transactions_amount_not_null CHECK (amount IS NOT NULL),
    ADD CONSTRAINT transactions_posted_date_not_null CHECK (posted_date IS NOT NULL);

-- 2. Decouple Skills: Retire the old 'override-category' and register new specific tools
UPDATE public.bh_skills SET is_active = false WHERE name = 'override-category';

-- New Tool: categorize-merchant (The "Propose" tool)
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only)
VALUES (
    'categorize-merchant',
    'Set a general rule for a merchant (e.g. "Amazon is Shopping"). Returns a preview of transactions that would be updated.',
    'native://categorize-merchant',
    'POST',
    '{
        "type": "object",
        "required": ["description_pattern", "category_name"],
        "properties": {
            "description_pattern": {"type": "string", "description": "The merchant name or pattern (e.g. \"Amazon\", \"Netflix\")"},
            "category_name": {"type": "string", "description": "The category (e.g. \"Shopping\", \"Dining\")"}
        }
    }'::jsonb,
    'single',
    true,
    '{}',
    now(),
    false
);

-- New Tool: categorize-transaction (The "Specific Fix" tool)
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only)
VALUES (
    'categorize-transaction',
    'Update the category for one specific transaction by its ID.',
    'native://categorize-transaction',
    'POST',
    '{
        "type": "object",
        "required": ["transaction_id", "category_name"],
        "properties": {
            "transaction_id": {"type": "string", "description": "The specific TRN-XXX id"},
            "category_name": {"type": "string", "description": "The category (e.g. \"Shopping\")"}
        }
    }'::jsonb,
    'single',
    true,
    '{}',
    now(),
    false
);

-- New Tool: commit-bulk-update (The "Commit" tool)
INSERT INTO public.bh_skills (name, description, webhook_url, http_method, param_schema, response_hint, is_active, restricted_users, created_at, is_read_only)
VALUES (
    'commit-bulk-update',
    'Execute a previously proposed bulk update. ONLY call this if the user says "yes" or "proceed" to a preview.',
    'native://commit-bulk-update',
    'POST',
    '{
        "type": "object",
        "required": ["description_pattern", "category_name"],
        "properties": {
            "description_pattern": {"type": "string", "description": "The merchant pattern to update"},
            "category_name": {"type": "string", "description": "The category to apply"}
        }
    }'::jsonb,
    'single',
    true,
    '{}',
    now(),
    false
);

-- 3. Layer 1 Determinism: Register L1 pattern for "X is Y"
INSERT INTO public.bh_patterns (rule, rule_type, skill_id, param_template, description, priority, is_active)
VALUES (
    '(?i)^([A-Za-z0-9\.]+)\s+(?:is|is\s+always|should\s+be)\s+([A-Za-z_]+)$',
    'regex',
    (SELECT id FROM bh_skills WHERE name = 'categorize-merchant'),
    '{"description_pattern": "$1", "category_name": "$2"}',
    'Deterministic "Merchant is Category" rule',
    60,
    true
);
