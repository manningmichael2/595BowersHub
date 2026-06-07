-- ============================================================
-- Rename `finance-query` skill to `ask-db` (TODO #30)
-- The skill is misnamed: it's universal NL->SQL across ALL
-- schemas (public, inventory, files, cook, house), not just
-- finance. Aligns with the AnythingLLM `ask-db` convention.
-- The underlying n8n webhook URL stays /webhook/finance-query
-- (that's the actual endpoint path on the n8n side).
-- ============================================================

-- Rename the skill and rewrite the description
UPDATE public.bh_skills
SET
    name = 'ask-db',
    description = 'Ask any question about your stored data in natural language. Translates to SQL and queries the database. Covers transactions, accounts, balances, inventory (tools, router bits, saw blades, wood), files, recipes, house data — every schema you have access to. Use this for any "how many", "show me", "what did I", "list my X" question.'
WHERE name = 'finance-query';

-- Update the Finance workspace system prompt to use the new name
-- and to be honest about scope (it's a personal AI assistant, not
-- only a financial advisor — it just happens to be the workspace
-- where finance data is the primary focus).
UPDATE public.bh_workspaces
SET system_prompt = 'You are BowersHub AI acting as a personal financial advisor. You have access to all bank accounts, transactions, and spending data. For complex questions, use the ask-db skill (natural-language SQL across all your data). For common lookups, use balances, transactions, or spending-summary. Format monetary amounts with $ and two decimal places. Negative amounts are spending, positive are income. Exclude transfers from spending analysis unless specifically asked.'
WHERE name = 'Finance';
