-- Migration 013: Add is_investment flag and investment detection
-- Investments are money flowing to/from brokerage accounts — not real income/expense.
-- We track them separately so the spend/income totals reflect actual cash flow.

ALTER TABLE public.transactions
    ADD COLUMN IF NOT EXISTS is_investment BOOLEAN NOT NULL DEFAULT false;

CREATE INDEX IF NOT EXISTS idx_transactions_is_investment
    ON public.transactions(is_investment)
    WHERE is_investment = true;

-- Backfill existing data: flag obvious investment transactions
-- Pattern 1: Description starts with "Investment:" (Fidelity-style fund purchase/sale)
UPDATE public.transactions
SET is_investment = true
WHERE description ILIKE 'Investment:%'
   OR description ILIKE 'Transfer Investment%'
   OR description ILIKE '%Fidelity Investment%'
   OR description ILIKE '%Vanguard Investment%'
   OR description ILIKE '%Schwab%'
   OR description ILIKE '%Brokerage%'
   OR description ILIKE '%FID BKG SVC LLC%';

-- Comment for documentation
COMMENT ON COLUMN public.transactions.is_investment IS
    'True if this transaction represents a flow to/from an investment account (brokerage, fund purchase, dividend reinvestment). Not counted as real income or expense.';
