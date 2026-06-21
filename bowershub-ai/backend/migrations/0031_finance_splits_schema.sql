-- 0031 — Transaction splits schema + the allocation-aware rollup view.
--
-- Additive/nullable DDL, migrator-owned (C7). Implements finance-budgets-splits
-- Task 1 (R1.1, R1.8, R2.1, R2.2, R4.1). A split parent keeps its amount but
-- becomes a container (category_id NULL, is_split=true); children are real
-- finance.transactions rows with parent_id set, carrying their own category_id +
-- amount and inheriting the parent's posted_date/account_id. No behavior change
-- until a transaction is actually split. standard_conforming_strings is on.
--
-- Refs: .kiro/specs/finance-budgets-splits/{requirements,design}.md.

-- 1. Split columns on transactions (R1.1, R1.8).
ALTER TABLE finance.transactions
    ADD COLUMN IF NOT EXISTS parent_id varchar(128),
    ADD COLUMN IF NOT EXISTS is_split boolean NOT NULL DEFAULT false;

-- Child → parent self-FK; deleting a parent removes its children (R1.8).
DO $$ BEGIN
    ALTER TABLE finance.transactions
        ADD CONSTRAINT transactions_parent_id_fkey
        FOREIGN KEY (parent_id) REFERENCES finance.transactions(id) ON DELETE CASCADE;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS transactions_parent_id_idx ON finance.transactions (parent_id);

-- 2. Recreate the migrator-owned public.transactions view to expose parent_id +
--    is_split (R4.1). Mirrors 0029; recreated under the migrator so ownership
--    stays correct, then re-granted to finance_reader.
DROP VIEW IF EXISTS public.transactions;
CREATE VIEW public.transactions AS
SELECT
    t.id,
    t.account_id,
    a.account_name,
    a.account_type,
    t.posted_date,
    t.amount,
    t.description,
    t.memo,
    t.pending,
    t.category_id,
    c.name AS category_name,
    t.merchant_key,
    t.categorized_by_tier,
    t.categorization_confidence,
    t.user_category_override,
    t.is_transfer,
    t.is_transfer_manual,
    t.transfer_id,
    t.cleared,
    t.parent_id,
    t.is_split,
    t.house_tag,
    t.house_tag_manual,
    t.created_at,
    t.updated_at,
    t.source,
    t.is_investment
FROM finance.transactions t
LEFT JOIN finance.categories c ON c.id = t.category_id
LEFT JOIN finance.accounts a ON a.id = t.account_id;

GRANT SELECT ON public.transactions TO finance_reader;

-- 3. The single allocation-aware rollup source (R2.1 + R2.2). Bakes ALL three
--    exclusions in one place so no caller can drift:
--      - is_split = false      → split children counted (they carry category_id),
--                                split parents excluded (no double-count)
--      - is_transfer = false   → canonical "real spending/income" filter
--      - is_investment = false   (resolves the finance.py-vs-dashboard.py mismatch)
--    Spend = amount < 0, income = amount > 0; both read THIS view.
DROP VIEW IF EXISTS public.real_activity;
CREATE VIEW public.real_activity AS
SELECT
    t.id,
    t.account_id,
    t.category_id,
    t.posted_date,
    t.amount
FROM finance.transactions t
WHERE t.is_split = false
  AND t.is_transfer = false
  AND t.is_investment = false;

GRANT SELECT ON public.real_activity TO finance_reader;
