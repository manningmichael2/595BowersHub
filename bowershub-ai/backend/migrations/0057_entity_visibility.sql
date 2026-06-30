-- 0057 — Captured-fact visibility: per-entity private vs shared.
--
-- The household shares context by design, so auto-captured facts (and manual
-- /remember + finance) default to 'shared'. This flag lets a user mark a
-- conversation's captures 'private' (scoped to created_by on the recall path) via
-- a Shared/Private toggle next to the chat bar (and a per-fact flip in the
-- Captured Facts admin panel) when they DON'T want something fed to the shared
-- household memory. Recall (hybrid_retrieval._search_entities) previously filtered
-- only on is_active; it now honors this flag.
--
-- Column default is 'shared', so every existing entity and every new capture
-- stays shared unless the user explicitly chooses Private. No backfill needed —
-- shared-by-default is the intended state for pre-existing rows too.
--
-- Forward-only + idempotent.

ALTER TABLE public.bh_entities
    ADD COLUMN IF NOT EXISTS visibility text NOT NULL DEFAULT 'shared';

-- Constrain to the two known values. Dropped-then-added so a re-run is clean.
ALTER TABLE public.bh_entities
    DROP CONSTRAINT IF EXISTS bh_entities_visibility_check;
ALTER TABLE public.bh_entities
    ADD CONSTRAINT bh_entities_visibility_check
    CHECK (visibility IN ('private', 'shared'));

-- Keep the recall filter (is_active AND (visibility='shared' OR created_by=$me))
-- index-friendly.
CREATE INDEX IF NOT EXISTS ix_bh_entities_visibility_owner
    ON public.bh_entities (visibility, created_by)
    WHERE is_active;
