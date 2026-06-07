-- ============================================================
-- BowersHub AI: Seed Model Rates
-- Cost rates for AI models (per million tokens).
-- Updated via admin UI without code changes.
-- ============================================================

INSERT INTO public.bh_model_rates (provider, model_id, display_name, input_cost_per_mtok, output_cost_per_mtok, supports_vision, supports_tools, max_output_tokens)
VALUES
    -- Anthropic Direct
    ('anthropic', 'claude-haiku-4-5-20251001', 'Claude Haiku 4.5', 0.80, 4.00, true, true, 8192),
    ('anthropic', 'claude-sonnet-4-5', 'Claude Sonnet 4.5', 3.00, 15.00, true, true, 8192),
    ('anthropic', 'claude-sonnet-4', 'Claude Sonnet 4', 3.00, 15.00, true, true, 8192),
    ('anthropic', 'claude-opus-4-5', 'Claude Opus 4', 15.00, 75.00, true, true, 8192),

    -- AWS Bedrock (same models, same pricing — Bedrock doesn't add markup for Claude)
    ('bedrock', 'us.anthropic.claude-haiku-4-5-20251001-v1:0', 'Haiku 4.5 (Bedrock)', 0.80, 4.00, true, true, 8192),
    ('bedrock', 'us.anthropic.claude-sonnet-4-5-v1:0', 'Sonnet 4.5 (Bedrock)', 3.00, 15.00, true, true, 8192),
    ('bedrock', 'us.anthropic.claude-sonnet-4-v1:0', 'Sonnet 4 (Bedrock)', 3.00, 15.00, true, true, 8192),
    ('bedrock', 'us.anthropic.claude-opus-4-5-v1:0', 'Opus 4 (Bedrock)', 15.00, 75.00, true, true, 8192),

    -- Ollama (local — zero cost)
    ('ollama', 'hermes3:8b', 'Hermes 3 8B (Local)', 0.00, 0.00, false, true, 4096),
    ('ollama', 'llama3.2:3b', 'Llama 3.2 3B (Local)', 0.00, 0.00, false, false, 4096),
    ('ollama', 'qwen2.5:7b', 'Qwen 2.5 7B (Local)', 0.00, 0.00, false, true, 4096)

ON CONFLICT (model_id) DO UPDATE SET
    input_cost_per_mtok = EXCLUDED.input_cost_per_mtok,
    output_cost_per_mtok = EXCLUDED.output_cost_per_mtok,
    supports_vision = EXCLUDED.supports_vision,
    supports_tools = EXCLUDED.supports_tools,
    max_output_tokens = EXCLUDED.max_output_tokens,
    updated_at = now();
