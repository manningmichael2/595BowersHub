-- 0057 — Captured-fact privacy: per-entity visibility (private vs shared).
--
-- The Context Harvester (services/context_capture.py, wired on in 0056) silently
-- extracts durable facts from every conversation and mirrors them into
-- bh_entities. Recall (hybrid_retrieval._search_entities) filtered only on
-- is_active, so entities were GLOBAL to every household member — a sensitive or
-- surprise thing said in one person's 1:1 chat could auto-surface in another's
-- recall. Nobody chose to share it; the machine promoted it.
--
-- This adds a visibility flag. Auto-captured facts default to 'private' (scoped
-- to created_by on the recall path); manual /remember + finance entities stay
-- 'shared'. A Personal/Shared toggle next to the chat bar (and a flip in the
-- Captured Facts admin panel) is how a user consciously shares.
--
-- Column default is 'shared' so EXISTING manual entities keep their current
-- behavior untouched; only the harvester writes 'private' going forward.
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

-- Backfill: make pre-existing auto-captured facts private, but only where they
-- are attributable to a person (created_by NOT NULL) — a private fact with no
-- owner can't be scoped to anyone, so it would become invisible to all. Those
-- (and all manual entities) stay 'shared'. Guarded so a re-run is a no-op once
-- rows are already private.
UPDATE public.bh_entities
    SET visibility = 'private'
    WHERE source = 'context_capture'
      AND created_by IS NOT NULL
      AND visibility = 'shared';

-- Keep the recall filter (is_active AND (visibility='shared' OR created_by=$me))
-- index-friendly.
CREATE INDEX IF NOT EXISTS ix_bh_entities_visibility_owner
    ON public.bh_entities (visibility, created_by)
    WHERE is_active;
