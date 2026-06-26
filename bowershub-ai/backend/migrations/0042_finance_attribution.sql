-- 0042 — finance attribution (R4.1 / D5 / D6 / D7).
--
-- Adds created_by / updated_by to the user-writable finance tables so a manual
-- edit records WHO made it. Additive, nullable, no backfill: existing rows stay
-- NULL (historical → "no hint" in the UI), bank-synced rows stay NULL ("Bank
-- sync"), and only edits made through the finance write APIs after this point
-- carry an attribution.
--
-- FK → public.bh_users ON DELETE SET NULL: deactivation is the norm (users are
-- never hard-deleted — D7), but if a user row is ever removed the attribution
-- degrades to NULL rather than breaking the FK or orphaning a dangling id.
--
-- No new GRANTs: ADD COLUMN inherits the table's existing privileges, so
-- bowershub_app keeps INSERT/UPDATE and finance_reader keeps SELECT on the new
-- columns automatically. System/sync writers (simplefin_sync, nightly jobs)
-- write these as NULL (D6) — nothing to grant there either.

ALTER TABLE finance.transactions
    ADD COLUMN IF NOT EXISTS created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL;

ALTER TABLE finance.budgets
    ADD COLUMN IF NOT EXISTS created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL;

ALTER TABLE finance.categories
    ADD COLUMN IF NOT EXISTS created_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS updated_by integer REFERENCES public.bh_users(id) ON DELETE SET NULL;
