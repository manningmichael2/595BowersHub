-- 0008_backfill_message_costs.sql — re-cost historical messages at corrected rates (§9.6).
--
-- The Cost dashboard (/api/admin/cost) sums bh_messages.cost_usd, which is FROZEN onto
-- each message at send time. The 0006/0007 price corrections are forward-only, so
-- historical rows kept their old (wrong) cost. This recomputes cost_usd for every
-- message whose model_used exactly matches a catalog row, using that row's current
-- price — identical formula and round(6) to services/model_catalog.py:cost_for's
-- exact-match path, so backfilled history matches how new messages are costed.
--
-- Exact-match only (the dominant/only case here — all historical models are in the
-- catalog); rows whose model_used isn't in bh_model_rates keep their value. Guarded to
-- only-changed rows → idempotent. No-op on a fresh build (bh_messages isn't seeded).
-- This MUTATES historical cost records in place; it's a correction of always-wrong
-- values, not a rewrite of legitimately-different historical pricing. Forward-only.

UPDATE public.bh_messages m SET
    cost_usd = round(
        (m.input_tokens  * r.input_cost_per_mtok  / 1000000.0)
      + (m.output_tokens * r.output_cost_per_mtok / 1000000.0), 6)
FROM public.bh_model_rates r
WHERE r.model_id = m.model_used
  AND m.cost_usd IS NOT NULL
  AND m.cost_usd <> round(
        (m.input_tokens  * r.input_cost_per_mtok  / 1000000.0)
      + (m.output_tokens * r.output_cost_per_mtok / 1000000.0), 6);
