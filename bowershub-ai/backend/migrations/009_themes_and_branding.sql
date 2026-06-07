-- ============================================================
-- BowersHub AI: Themes and Branding (spec: bowershub-ai-enhancements)
-- Adds:
--   - public.bh_themes            (preset + custom theme palettes)
--   - public.bh_platform_settings (key/value platform-wide config)
-- Seeds:
--   - 4 preset themes (Dark Navy, Light Stone, Forest, Mono)
--   - 4 platform settings rows (default_theme_id, app_icon_version,
--     app_icon_active_filename, app_icon_previous_filename)
-- _Requirements: R1.1, R1.5, R2.4, R2.5, R3.7
-- ============================================================

-- ---------- Tables ----------

CREATE TABLE IF NOT EXISTS public.bh_themes (
    id              SERIAL PRIMARY KEY,
    name            TEXT NOT NULL,
    slug            TEXT NOT NULL,
    is_preset       BOOLEAN NOT NULL DEFAULT false,
    -- owner_id semantics:
    --   NULL + is_preset=true   -> built-in preset (visible to all, undeletable)
    --   NULL + is_preset=false  -> admin-published custom theme (visible to all)
    --   <user_id>               -> personal custom theme (visible only to that user + admin)
    owner_id        INTEGER REFERENCES public.bh_users(id) ON DELETE CASCADE,
    tokens_json     JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (slug, owner_id)
);

CREATE INDEX IF NOT EXISTS idx_bh_themes_owner
    ON public.bh_themes(owner_id);
CREATE INDEX IF NOT EXISTS idx_bh_themes_preset
    ON public.bh_themes(is_preset);

CREATE TABLE IF NOT EXISTS public.bh_platform_settings (
    key             TEXT PRIMARY KEY,
    value_json      JSONB NOT NULL,
    updated_by      INTEGER REFERENCES public.bh_users(id),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------- Seed: preset themes ----------
-- All token values are 6-digit hex. Matches the token shape defined in
-- design.md ("Database Changes"): background, surface, primary, accent,
-- text, text_muted, border, danger, success.
-- Postgres UNIQUE treats NULLs as distinct, so re-running this seed
-- would create duplicates — guard with NOT EXISTS instead of ON CONFLICT.

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Dark Navy', 'dark-navy', true, NULL, '{
    "background":  "#0f0f1a",
    "surface":     "#1a1a2e",
    "primary":     "#6366f1",
    "accent":      "#818cf8",
    "text":        "#e5e7eb",
    "text_muted":  "#94a3b8",
    "border":      "#374151",
    "danger":      "#ef4444",
    "success":     "#22c55e"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'dark-navy' AND owner_id IS NULL
);

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Light Stone', 'light-stone', true, NULL, '{
    "background":  "#f8f7f4",
    "surface":     "#ffffff",
    "primary":     "#4f46e5",
    "accent":      "#6366f1",
    "text":        "#1f2937",
    "text_muted":  "#6b7280",
    "border":      "#e5e7eb",
    "danger":      "#dc2626",
    "success":     "#16a34a"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'light-stone' AND owner_id IS NULL
);

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Forest', 'forest', true, NULL, '{
    "background":  "#0f1f17",
    "surface":     "#1a2e22",
    "primary":     "#22c55e",
    "accent":      "#4ade80",
    "text":        "#e5f7ec",
    "text_muted":  "#94a3b8",
    "border":      "#2d3f33",
    "danger":      "#ef4444",
    "success":     "#22c55e"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'forest' AND owner_id IS NULL
);

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Mono', 'mono', true, NULL, '{
    "background":  "#000000",
    "surface":     "#1a1a1a",
    "primary":     "#ffffff",
    "accent":      "#d1d5db",
    "text":        "#e5e7eb",
    "text_muted":  "#9ca3af",
    "border":      "#374151",
    "danger":      "#ef4444",
    "success":     "#22c55e"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'mono' AND owner_id IS NULL
);

-- ---------- Seed: platform settings ----------
-- default_theme_id points at the Dark Navy preset row inserted above.
-- The lookup-by-slug pattern keeps the seed deterministic even though
-- the SERIAL id is environment-specific.
-- app_icon_version uses the migration-time epoch so the manifest URL
-- gets a unique cache-busting query string on first deploy.
-- _Requirements: R1.3, R2.4, R3.7

INSERT INTO public.bh_platform_settings (key, value_json)
SELECT 'default_theme_id',
       jsonb_build_object('theme_id', (
           SELECT id FROM public.bh_themes
           WHERE slug = 'dark-navy' AND owner_id IS NULL
       ))
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_platform_settings WHERE key = 'default_theme_id'
);

INSERT INTO public.bh_platform_settings (key, value_json)
SELECT 'app_icon_version',
       jsonb_build_object('version', extract(epoch FROM now())::bigint::text)
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_platform_settings WHERE key = 'app_icon_version'
);

INSERT INTO public.bh_platform_settings (key, value_json)
SELECT 'app_icon_active_filename',
       jsonb_build_object('filename', 'icon-set-default')
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_platform_settings WHERE key = 'app_icon_active_filename'
);

INSERT INTO public.bh_platform_settings (key, value_json)
SELECT 'app_icon_previous_filename',
       jsonb_build_object('filename', NULL)
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_platform_settings WHERE key = 'app_icon_previous_filename'
);
