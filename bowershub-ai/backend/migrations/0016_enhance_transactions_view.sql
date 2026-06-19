-- Enhance the public.transactions view to include human-readable names.
-- This satisfies the requirement to see 'category_name' and 'account_name'
-- instead of just IDs when querying via ask-db or raw SQL.

DROP VIEW IF EXISTS public.transactions;

CREATE VIEW public.transactions AS
SELECT 
    t.id,
    t.account_id,
    a.account_name,
    t.posted_date,
    t.amount,
    t.description,
    t.memo,
    t.pending,
    t.category_id,
    c.name AS category_name,
    t.user_category_override,
    t.is_transfer,
    t.is_transfer_manual,
    t.house_tag,
    t.house_tag_manual,
    t.created_at,
    t.updated_at,
    t.source,
    t.is_investment
FROM finance.transactions t
LEFT JOIN finance.categories c ON c.id = t.category_id
LEFT JOIN finance.accounts a ON a.id = t.account_id;

-- Grant permissions to the finance_reader role (used by ask-db)
GRANT SELECT ON public.transactions TO finance_reader;
