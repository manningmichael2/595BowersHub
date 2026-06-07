-- ============================================================================
-- 003 — Email-derived transactions
-- ============================================================================
-- Adds a `source` column so we can distinguish where a transactions row came
-- from (SimpleFin sync vs email receipts vs future manual entry), plus a
-- synthetic account row to hold email-derived spending that isn't tied to
-- a real bank account in SimpleFin.
--
-- Design rationale:
--   - transactions.id is a varchar(128); upstream IDs from SimpleFin are stable.
--     For email imports, we mint id = 'email:' || files.assets.id
--     (asset_id is a UUID, so guaranteed unique).
--   - account_id is NOT NULL with an FK to accounts. We need a row that
--     represents "this came from an email, no bank involved". 'EMAIL_RECEIPT'
--     is that pseudo-account. Future: support attaching a real account_id
--     when the user knows which card was used.
--
-- Idempotent: safe to re-run.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Add source column to transactions
-- ---------------------------------------------------------------------------
ALTER TABLE public.transactions
    ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'simplefin';

CREATE INDEX IF NOT EXISTS idx_transactions_source
    ON public.transactions (source);

COMMENT ON COLUMN public.transactions.source IS
    'Where this row originated: simplefin (default, bank sync), email (parsed from a receipt email), manual.';

-- ---------------------------------------------------------------------------
-- Synthetic account for email-imported receipts.
-- Schema is dictated by whatever exists already; let the INSERT be defensive.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    has_name        BOOLEAN;
    has_account_name BOOLEAN;
    has_org_name    BOOLEAN;
    has_currency    BOOLEAN;
    has_balance     BOOLEAN;
    has_acct_type   BOOLEAN;
    sql_columns     TEXT;
    sql_values      TEXT;
BEGIN
    -- Bail out if the row already exists.
    IF EXISTS (SELECT 1 FROM public.accounts WHERE id = 'EMAIL_RECEIPT') THEN
        RAISE NOTICE 'EMAIL_RECEIPT account already exists; skipping insert.';
        RETURN;
    END IF;

    -- Inspect available columns so we only set ones that exist.
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='name')
      INTO has_name;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='account_name')
      INTO has_account_name;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='org_name')
      INTO has_org_name;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='currency')
      INTO has_currency;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='balance')
      INTO has_balance;
    SELECT EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='accounts' AND column_name='account_type')
      INTO has_acct_type;

    sql_columns := 'id';
    sql_values  := quote_literal('EMAIL_RECEIPT');
    IF has_name THEN
        sql_columns := sql_columns || ', name';
        sql_values  := sql_values  || ', ' || quote_literal('Email Receipts (synthetic)');
    END IF;
    IF has_account_name THEN
        sql_columns := sql_columns || ', account_name';
        sql_values  := sql_values  || ', ' || quote_literal('Synthetic (no bank)');
    END IF;
    IF has_org_name THEN
        sql_columns := sql_columns || ', org_name';
        sql_values  := sql_values  || ', ' || quote_literal('Email Receipts');
    END IF;
    IF has_currency THEN
        sql_columns := sql_columns || ', currency';
        sql_values  := sql_values  || ', ' || quote_literal('USD');
    END IF;
    IF has_balance THEN
        sql_columns := sql_columns || ', balance';
        sql_values  := sql_values  || ', 0';
    END IF;
    IF has_acct_type THEN
        sql_columns := sql_columns || ', account_type';
        sql_values  := sql_values  || ', ' || quote_literal('synthetic');
    END IF;

    EXECUTE format('INSERT INTO public.accounts (%s) VALUES (%s)', sql_columns, sql_values);
    RAISE NOTICE 'Inserted EMAIL_RECEIPT account.';
END $$;
