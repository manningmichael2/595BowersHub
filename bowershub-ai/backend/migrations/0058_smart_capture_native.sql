-- 0058_smart_capture_native.sql
-- Machinery for the native smart-capture engine (n8n-decommission spec, S0).
-- Forward-only + idempotent. This lands the switch DARK: engine defaults to
-- 'n8n', so behavior is unchanged until the cutover (S3) flips the row. Adds no
-- schema to existing capture-target tables — committers reuse them as-is.

-- Engine switch: 'n8n' | 'native' | 'shadow'. Default 'n8n' (fail-safe: n8n is
-- the reachable fallback/rollback target until decommission). Un-cached reads in
-- config.py mean flipping this row takes effect on the next request, no restart.
INSERT INTO public.bh_platform_settings (key, value_json)
VALUES ('smart_capture.engine', '"n8n"'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- HMAC-SHA256 secret for extract tokens: 64 hex chars = 32 bytes. DB-driven, no
-- code constant (NO-HARDCODING). pgcrypto (gen_random_bytes) is present from
-- 0001_baseline. Generated once here; ON CONFLICT keeps it stable across re-runs.
INSERT INTO public.bh_platform_settings (key, value_json)
VALUES ('smart_capture.token_secret', to_jsonb(encode(gen_random_bytes(32), 'hex')))
ON CONFLICT (key) DO NOTHING;

-- Native vision (process-asset) gate. While false, an image-based extract proxies
-- to n8n even under engine=native, so TEXT capture can cut over before IMAGE
-- (the M4 per-request fallback). Flipped true once the process-asset port lands.
INSERT INTO public.bh_platform_settings (key, value_json)
VALUES ('smart_capture.process_asset_native', 'false'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- Workspace the admin-only inbox extract routes (/inbox/ai-extract, url-extract)
-- attribute captures to. NULL → resolved at runtime to the admin's default
-- workspace (never a hardcoded id — NO-HARDCODING).
INSERT INTO public.bh_platform_settings (key, value_json)
VALUES ('smart_capture.inbox_workspace_id', 'null'::jsonb)
ON CONFLICT (key) DO NOTHING;

-- Idempotency guard for per-intent commits. dedup_key = sha256(hmac || intent
-- hash); an exact (token, intent) replay within the 30-min window returns the
-- original result_json and writes nothing (see commit.py).
CREATE TABLE IF NOT EXISTS public.bh_smart_capture_commits (
    dedup_key  text PRIMARY KEY,
    result_json jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
