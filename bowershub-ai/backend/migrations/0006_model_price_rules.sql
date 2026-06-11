-- 0006_model_price_rules.sql — DB-driven provisional pricing for model discovery (§9.6).
--
-- Kills the last hardcoded pricing path: services/model_catalog.py:_infer_pricing's
-- name heuristic (haiku→0.8/4, opus→15/75, sonnet/local→3/15) was a NO-HARDCODING
-- (Rule #1) violation AND stale — it priced new Opus 4.6/4.7/4.8 at the pre-4.5
-- $15/$75 and local/Ollama models at $3/$15 instead of $0.
--
-- This table is the operator-curated source of provisional prices for NEWLY discovered
-- models (R3.2): on insert, discovery picks the highest-priority rule whose LIKE
-- `pattern` matches the model_id (optionally scoped by provider) and uses its rate,
-- still flagging needs_price_confirmation=true. The cost MISS-path (cost_for, R3.3)
-- keeps the byte-identical _infer_pricing floor so the Task 8 cost-parity gate holds.
--
-- Seed rates are grounded in Anthropic's canonical pricing (per the claude-api ref,
-- 2026-06): Fable 5 10/50; Opus 4.5/4.6/4.7/4.8 5/25; Opus 4.0/4.1 (pre-drop) 15/75;
-- Sonnet 3/15; Haiku 1/5; any Ollama/local 0/0. Forward-only; runs as bowershub_app
-- (owns public.*), one transaction; never edit once shipped.

-- === The rules table ========================================================
CREATE TABLE IF NOT EXISTS public.bh_model_price_rules (
    id                   serial PRIMARY KEY,
    provider             text,                              -- NULL = any provider; else exact match (e.g. 'ollama')
    pattern              text        NOT NULL,              -- SQL LIKE pattern matched against model_id
    input_cost_per_mtok  numeric(10,4) NOT NULL,
    output_cost_per_mtok numeric(10,4) NOT NULL,
    priority             integer     NOT NULL DEFAULT 50,   -- higher wins; ties break on longer (more specific) pattern
    note                 text,
    created_at           timestamptz NOT NULL DEFAULT now(),
    updated_at           timestamptz NOT NULL DEFAULT now()
);

-- One active rule per (provider, pattern); re-running the migration is idempotent.
CREATE UNIQUE INDEX IF NOT EXISTS bh_model_price_rules_provider_pattern_idx
    ON public.bh_model_price_rules (COALESCE(provider, '*'), pattern);

-- === Seed rules (grounded in canonical pricing) =============================
-- Versioned Opus rules at priority 100 so they beat the generic 'claude-opus-%'
-- current-tier fallback; family rules at 50. Local/Ollama is provider-scoped.
INSERT INTO public.bh_model_price_rules (provider, pattern, input_cost_per_mtok, output_cost_per_mtok, priority, note) VALUES
    (NULL,     'claude-fable-5%',   10.0000, 50.0000, 100, 'Fable 5 (canonical)'),
    (NULL,     'claude-opus-4-8%',   5.0000, 25.0000, 100, 'Opus 4.8 (canonical)'),
    (NULL,     'claude-opus-4-7%',   5.0000, 25.0000, 100, 'Opus 4.7 (canonical)'),
    (NULL,     'claude-opus-4-6%',   5.0000, 25.0000, 100, 'Opus 4.6 (canonical)'),
    (NULL,     'claude-opus-4-5%',   5.0000, 25.0000, 100, 'Opus 4.5 (canonical)'),
    (NULL,     'claude-opus-4-1%',  15.0000, 75.0000, 100, 'Opus 4.1 (pre-4.5 pricing)'),
    (NULL,     'claude-opus-4-0%',  15.0000, 75.0000, 100, 'Opus 4.0 (pre-4.5 pricing)'),
    (NULL,     'claude-opus-%',      5.0000, 25.0000,  50, 'Opus current-tier fallback'),
    (NULL,     'claude-sonnet-%',    3.0000, 15.0000,  50, 'Sonnet tier'),
    (NULL,     'claude-haiku-%',     1.0000,  5.0000,  50, 'Haiku 4.5 (canonical)'),
    ('ollama', '%',                  0.0000,  0.0000,  50, 'Local inference — no marginal cost')
ON CONFLICT (COALESCE(provider, '*'), pattern) DO NOTHING;

-- === Re-price the rows discovery flagged with the stale heuristic ============
-- Only touches needs_price_confirmation=true rows (provisional, not operator-owned),
-- so confirmed operator prices are never overwritten. Picks the same highest-priority
-- rule the service now uses. Leaves the flag set — the rule is a better DEFAULT, not a
-- human confirmation. Confirmed-but-stale rows (e.g. haiku 0.8/4) are intentionally
-- left for the operator to correct.
-- Best rule per flagged model computed by joining the two tables (DISTINCT ON picks
-- the highest-priority / longest-pattern match — same order the service uses), then
-- joined back to the target by model_id. Flagged rows with no matching rule keep
-- their existing value (the join simply doesn't produce a row for them).
UPDATE public.bh_model_rates r SET
    input_cost_per_mtok  = best.in_cost,
    output_cost_per_mtok = best.out_cost,
    updated_at           = now()
FROM (
    SELECT DISTINCT ON (rt.model_id)
        rt.model_id,
        pr.input_cost_per_mtok  AS in_cost,
        pr.output_cost_per_mtok AS out_cost
    FROM public.bh_model_rates rt
    JOIN public.bh_model_price_rules pr
      ON (pr.provider IS NULL OR pr.provider = rt.provider)
     AND rt.model_id LIKE pr.pattern
    WHERE rt.needs_price_confirmation = true
    ORDER BY rt.model_id, pr.priority DESC, length(pr.pattern) DESC
) best
WHERE r.model_id = best.model_id;
