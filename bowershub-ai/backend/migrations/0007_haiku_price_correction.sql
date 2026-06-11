-- 0007_haiku_price_correction.sql — correct the stale Haiku 4.5 rate (§9.6).
--
-- The 0001 baseline seeded Haiku 4.5 at $0.80/$4.00 (an older rate) and marked it
-- price-confirmed, so the 0006 rules reprice — which only touches
-- needs_price_confirmation=true rows — left it alone. Canonical Haiku 4.5 pricing is
-- $1.00/$5.00 (per the claude-api reference, 2026-06), matching the
-- 'claude-haiku-%' price rule seeded in 0006. This corrects the confirmed row(s) so
-- cost tracking bills Haiku usage correctly, and a from-empty build is accurate.
--
-- Guarded to rows still at the stale $0.80/$4.00 so it's idempotent and won't clobber
-- a later operator change. Covers both the first-party and Bedrock Haiku rows (Bedrock
-- bills Anthropic's per-token list rate for the same model). Forward-only.

UPDATE public.bh_model_rates SET
    input_cost_per_mtok  = 1.0000,
    output_cost_per_mtok = 5.0000,
    updated_at           = now()
WHERE model_id LIKE '%claude-haiku-4-5%'
  AND input_cost_per_mtok  = 0.8000
  AND output_cost_per_mtok = 4.0000;
