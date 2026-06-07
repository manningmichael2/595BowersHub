-- ============================================================
-- Fix incorrect model IDs from initial seed
-- The Sonnet ID was incorrectly set to 20250514 (didn't exist).
-- Anthropic uses aliases like 'claude-sonnet-4-5' and dated IDs.
-- ============================================================

-- Remove old (wrong) entries
DELETE FROM public.bh_model_rates WHERE model_id IN (
    'claude-sonnet-4-5-20250514',
    'claude-sonnet-4-20250514',
    'claude-opus-4-20250514',
    'us.anthropic.claude-sonnet-4-5-20250514-v1:0',
    'us.anthropic.claude-sonnet-4-20250514-v1:0',
    'us.anthropic.claude-opus-4-20250514-v1:0'
);

-- Insert correct model IDs (using aliases that always point to latest version)
INSERT INTO public.bh_model_rates (provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens)
VALUES
    ('anthropic', 'claude-sonnet-4-5', 'Claude Sonnet 4.5', 3.00, 15.00, true, true, 8192),
    ('anthropic', 'claude-opus-4-5', 'Claude Opus 4.5', 15.00, 75.00, true, true, 8192),
    ('bedrock', 'us.anthropic.claude-sonnet-4-5-v1:0', 'Sonnet 4.5 (Bedrock)', 3.00, 15.00, true, true, 8192)
ON CONFLICT (model_id) DO UPDATE SET
    input_cost_per_mtok = EXCLUDED.input_cost_per_mtok,
    output_cost_per_mtok = EXCLUDED.output_cost_per_mtok,
    updated_at = now();
