-- 0049 — make lists household-shared by default.
--
-- bh_lists was per-user (resolved by name AND user_id), but a household grocery
-- list is inherently shared — both members add to and check off one list (matches
-- the shared finance/workspace model; bh_list_items.added_by already anticipates
-- multiple contributors). Add an is_shared flag (default true): shared lists are
-- visible/editable household-wide regardless of which user created them; a list
-- can still be made private (is_shared=false) for a personal list (e.g. a gift
-- list). The lists service resolves shared lists first.
--
-- Existing rows default to shared — the feature was unregistered until 0048, so
-- there is effectively no private list data to over-share.

ALTER TABLE public.bh_lists
    ADD COLUMN IF NOT EXISTS is_shared boolean NOT NULL DEFAULT true;
