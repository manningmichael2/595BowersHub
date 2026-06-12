-- 0011_embedding_config.sql
-- Seed the embedding role and configuration (R1.2).

-- 0. Add is_embedding column to bh_model_rates.
ALTER TABLE public.bh_model_rates
    ADD COLUMN IF NOT EXISTS is_embedding boolean NOT NULL DEFAULT false;

-- 1. Pre-seed bge-m3 in bh_model_rates (FK target).
-- This ensures resolve_role('embed') works on a fresh boot before discovery.
-- cost_per_mtok is 0 for local Ollama models.
INSERT INTO public.bh_model_rates (
    provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok,
    is_embedding, is_active, last_seen_at
) VALUES (
    'ollama', 'bge-m3', 'Bge-M3 (Embedding)', 0, 0,
    true, true, now()
) ON CONFLICT (model_id) DO UPDATE SET 
    is_embedding = true, 
    is_active = true, 
    updated_at = now();

-- 2. Add the 'embed' role alias (FK depends on bh_model_rates).
-- Defaulting to bge-m3 which is the project-standard embedding model.
INSERT INTO public.bh_model_aliases (role, model_id)
VALUES ('embed', 'bge-m3')
ON CONFLICT (role) DO UPDATE SET model_id = EXCLUDED.model_id, updated_at = now();

-- 3. Add the 'embedding_config' platform setting (R1.2 / R3.4).
-- This drives the EmbeddingWorker's versioning and dimension checks.
INSERT INTO public.bh_platform_settings (key, value_json)
VALUES ('embedding_config', '{"model": "bge-m3", "dim": 1024, "version": 1, "metric": "cosine"}'::jsonb)
ON CONFLICT (key) DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = now();
