-- 0005_dynamic_model_discovery.sql — DB-driven model catalog foundation (§9.6).
--
-- Makes public.bh_model_rates the single source of truth for the model catalog:
--   * lifecycle + capability + price-confirm columns (discovery upserts these),
--   * a bh_model_aliases role table ("current haiku/sonnet/opus/local"),
--   * a bh_model_refresh_log audit table,
--   * DB-driven discovery config in bh_platform_settings.
--
-- This migration only adds schema + seed data; the discovery service, scheduler
-- job, and read/cost/resolver cutover land in later phases (P1–P5). Forward-only,
-- auto-applied by database.py in one transaction; never edit once shipped.
--
-- T0 note: the Anthropic Models API (`models.list()`) returns CANONICAL dated IDs
-- (claude-sonnet-4-5-20250929, claude-opus-4-5-20251101 …), not the bare forms in
-- the 0001 seed. So the role aliases are seeded to canonical IDs that discovery
-- actually refreshes, and discovery additionally never deactivates an alias target
-- (see 0006+/service layer). sonnet → 4.6 per the approved T0 decision.

-- === Lifecycle + capability + price-confirm columns (R1.3, R1.4, R3.2) ======
ALTER TABLE public.bh_model_rates
    ADD COLUMN IF NOT EXISTS is_active                   boolean     NOT NULL DEFAULT true,
    ADD COLUMN IF NOT EXISTS last_seen_at                timestamptz NOT NULL DEFAULT now(),
    ADD COLUMN IF NOT EXISTS missed_fetch_count          integer     NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS needs_price_confirmation    boolean     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS max_input_tokens            integer,                          -- context window, NULL until discovered
    ADD COLUMN IF NOT EXISTS supports_thinking           boolean     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS supports_effort             boolean     NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS supports_structured_outputs boolean     NOT NULL DEFAULT false;

-- Explicit, auditable backfill of the existing seed rows (the column DEFAULTs already
-- cover a from-zero build; this makes the intent explicit and is a harmless no-op there).
-- Admin-curated rows must not be falsely flagged or hidden — NFR data-safety.
UPDATE public.bh_model_rates
   SET is_active = true,
       last_seen_at = now(),
       missed_fetch_count = 0,
       needs_price_confirmation = false;

-- === Canonical alias-target rows that models.list() returns but 0001 lacks ===
-- (id auto-assigned via bh_model_rates_id_seq). Prices are operator-known current
-- rates (seed data, like the 8 existing rows); discovery refreshes capabilities later.
INSERT INTO public.bh_model_rates
    (provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok,
     supports_vision, supports_tools, max_output_tokens)
VALUES
    ('anthropic', 'claude-sonnet-4-6',        'Claude Sonnet 4.6', 3.0000, 15.0000, true, true, 64000),
    ('anthropic', 'claude-opus-4-5-20251101', 'Claude Opus 4.5',   5.0000, 25.0000, true, true, 64000)
ON CONFLICT (model_id) DO NOTHING;

-- === Role/alias table — single source of truth for "current X" (R4.1) =======
-- FK on UNIQUE(model_id) guarantees a role can never point at a non-existent model.
CREATE TABLE IF NOT EXISTS public.bh_model_aliases (
    role        text PRIMARY KEY,                                              -- 'haiku','sonnet','opus','local'
    model_id    text NOT NULL REFERENCES public.bh_model_rates(model_id),
    updated_by  integer,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Day-one alias seed → canonical discoverable IDs (approved T0 decision).
INSERT INTO public.bh_model_aliases (role, model_id) VALUES
    ('haiku',  'claude-haiku-4-5-20251001'),   -- seed row id 1 (already canonical + discoverable)
    ('sonnet', 'claude-sonnet-4-6'),           -- inserted above; current best Sonnet
    ('opus',   'claude-opus-4-5-20251101'),    -- inserted above; canonical dated Opus
    ('local',  'llama3.2:3b')                  -- seed row id 10 (Ollama; OllamaDiscoverySource keeps it fresh)
ON CONFLICT (role) DO NOTHING;

-- Guard: abort the migration if any seeded role fails to resolve to an ACTIVE row,
-- so a typo can never silently go dark on deploy (R4.1). References only model_ids
-- that exist after the inserts above; a from-zero 0001→…→0005 build also passes.
DO $$
BEGIN
    IF (SELECT count(*)
          FROM public.bh_model_aliases a
          JOIN public.bh_model_rates r
            ON r.model_id = a.model_id AND r.is_active) <> 4 THEN
        RAISE EXCEPTION 'model alias seed failed: not all roles resolve to an active model row';
    END IF;
END $$;

-- === Refresh audit log (R2.5 observability) =================================
CREATE TABLE IF NOT EXISTS public.bh_model_refresh_log (
    id            serial PRIMARY KEY,
    ran_at        timestamptz NOT NULL DEFAULT now(),
    trigger       text        NOT NULL,           -- 'scheduled' | 'admin'
    complete      boolean     NOT NULL,
    added         integer     NOT NULL DEFAULT 0,
    deactivated   integer     NOT NULL DEFAULT 0,
    reactivated   integer     NOT NULL DEFAULT 0,
    price_flagged integer     NOT NULL DEFAULT 0,
    summary       jsonb
);

-- === DB-driven discovery config (Rule #1; R2.2) =============================
INSERT INTO public.bh_platform_settings (key, value_json) VALUES
    ('model_discovery_interval_hours', '{"hours": 24}'),    -- default daily; scheduler enforces a floor (>= 6h)
    ('model_discovery_stale_misses',   '{"count": 3}'),     -- N consecutive complete-fetch misses before deactivation
    ('model_discovery_enabled',        '{"enabled": true}') -- scheduled-write kill-lever (admin refresh still runs)
ON CONFLICT (key) DO NOTHING;
