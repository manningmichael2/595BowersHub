-- 0045 — per-account owner (household: tag whose account it is).
--
-- Adds owner_id to finance.accounts so a shared household can mark which member
-- an account belongs to (e.g. Manon's checking) and FILTER views by owner. This
-- is a DISPLAY/FILTER label only — finance data stays fully shared (everyone
-- still sees everything; the multiuser model has no per-user finance silos). It
-- is NOT an access boundary.
--
-- Additive, nullable, no backfill: existing accounts stay NULL = "Joint/Shared".
-- FK → public.bh_users ON DELETE SET NULL (mirrors 0042 attribution): if a user
-- is ever removed the tag degrades to Joint rather than breaking the FK.
--
-- No new GRANTs: ADD COLUMN inherits the table's existing privileges, so
-- bowershub_app keeps INSERT/UPDATE and finance_reader keeps SELECT.

ALTER TABLE finance.accounts
    ADD COLUMN IF NOT EXISTS owner_id integer REFERENCES public.bh_users(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS accounts_owner_id_idx ON finance.accounts (owner_id);
