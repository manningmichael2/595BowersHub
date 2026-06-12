-- 0009_semantic_role_names.sql — rename model role aliases to intent-based names.
--
-- bh_model_aliases (0005) keyed roles by vendor tier ('haiku'/'sonnet'/'opus'),
-- which couples the role names to one provider's product line. Rename them to what
-- each role MEANS so callers express intent, not a vendor SKU:
--   sonnet -> chat   (default conversation / L3 reasoning model)
--   haiku  -> fast   (cheap, fast utility worker — classification, tool routing)
--   opus   -> deep   (heavyweight reasoning; defined for future use, currently
--                     referenced by no caller — Opus is reachable via manual model
--                     selection, the router does not auto-escalate to it)
--   local  -> local  (unchanged — Ollama background work)
--
-- Behaviour-preserving: only the role KEY changes; each row's model_id is untouched,
-- so every alias keeps resolving to the same model. The matching resolve_role(...)
-- call sites and the cold-start fallback map in services/model_catalog.py are renamed
-- in the same change. Forward-only.
--
-- Idempotent: a re-run's WHERE clauses match nothing once renamed (the old keys are
-- gone). role is the PRIMARY KEY and the new keys don't pre-exist, so no conflict.

UPDATE public.bh_model_aliases SET role = 'chat', updated_at = now() WHERE role = 'sonnet';
UPDATE public.bh_model_aliases SET role = 'fast', updated_at = now() WHERE role = 'haiku';
UPDATE public.bh_model_aliases SET role = 'deep', updated_at = now() WHERE role = 'opus';

-- Guard: the four expected roles must each resolve to an ACTIVE model row, so a botched
-- rename can never silently leave a role pointing nowhere (mirrors the 0005 seed guard).
-- Passes on a from-empty 0001->...->0009 build (0005 seeds the old names, this renames).
DO $$
BEGIN
    IF (SELECT count(*)
          FROM public.bh_model_aliases a
          JOIN public.bh_model_rates r
            ON r.model_id = a.model_id AND r.is_active
         WHERE a.role IN ('chat', 'fast', 'deep', 'local')) <> 4 THEN
        RAISE EXCEPTION 'role rename failed: chat/fast/deep/local do not all resolve to an active model row';
    END IF;
END $$;
