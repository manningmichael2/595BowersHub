-- 0029 — Finance accounting schema (transfer matching · reconciliation · net worth).
--
-- Additive/nullable DDL, migrator-owned (C7). Implements the schema for
-- .kiro/specs/finance-accounting Task 1 (R4.2). All columns are nullable or have
-- defaults so existing rows are valid immediately and behavior is unchanged until
-- later tasks wire logic on top. standard_conforming_strings is on.
--
-- Refs: .kiro/specs/finance-accounting/{requirements,design}.md (R1.*, R2.*, R3.5, R4.2/3).

-- 1. Transfer linking + cleared status on transactions (R1.1, R1.5, R1.8, R2.2).
ALTER TABLE finance.transactions
    ADD COLUMN IF NOT EXISTS transfer_id varchar(128),
    ADD COLUMN IF NOT EXISTS transfer_link_manual boolean NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS cleared boolean NOT NULL DEFAULT false;

-- Self-referential FK: deleting one leg nulls the other's pointer (R1.8).
DO $$ BEGIN
    ALTER TABLE finance.transactions
        ADD CONSTRAINT transactions_transfer_id_fkey
        FOREIGN KEY (transfer_id) REFERENCES finance.transactions(id) ON DELETE SET NULL;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- No self-link (R1.8).
DO $$ BEGIN
    ALTER TABLE finance.transactions
        ADD CONSTRAINT transactions_no_self_transfer CHECK (transfer_id IS NULL OR transfer_id <> id);
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Partial unique → no two rows point at the same counterpart (enforces 1:1 with
-- the writer's symmetric set, R1.8). Plus a lookup index.
CREATE UNIQUE INDEX IF NOT EXISTS transactions_transfer_id_uniq
    ON finance.transactions (transfer_id) WHERE transfer_id IS NOT NULL;

-- 2. Net-worth + reconciliation columns on accounts (R2.4, R3.3).
ALTER TABLE finance.accounts
    ADD COLUMN IF NOT EXISTS reconciled_through_date date,
    ADD COLUMN IF NOT EXISTS include_in_net_worth boolean NOT NULL DEFAULT true;

-- 3. Reconciliation audit trail (R2.3). One row per reconcile event.
CREATE TABLE IF NOT EXISTS finance.reconciliations (
    id serial PRIMARY KEY,
    account_id varchar(128) NOT NULL REFERENCES finance.accounts(id),
    statement_date date NOT NULL,
    statement_balance numeric(12,2) NOT NULL,
    synced_balance numeric(12,2),
    delta numeric(12,2),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS reconciliations_account_idx ON finance.reconciliations (account_id, statement_date DESC);

-- 4. Balance-snapshot history for net-worth-over-time (R3.5). One row per
--    account per day; same-day re-sync is last-write-wins via the PK.
CREATE TABLE IF NOT EXISTS finance.balance_snapshots (
    account_id varchar(128) NOT NULL REFERENCES finance.accounts(id),
    snapshot_date date NOT NULL,
    balance numeric(12,2) NOT NULL,
    PRIMARY KEY (account_id, snapshot_date)
);

-- 5. DB-driven accounting config (R4.3) — mirrors finance.categorizer_config.
CREATE TABLE IF NOT EXISTS finance.accounting_config (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- 6. Recreate the migrator-owned public.transactions view to expose the new
--    transfer_id + cleared columns (R4.2). Mirrors 0022; recreated under the
--    migrator role so ownership stays correct, then re-grant to finance_reader.
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
