-- 0053 — University of Michigan "Maize & Blue" dark-OLED theme preset.
--
-- Adds a selectable theme (is_preset=true, owner_id=NULL → visible to every user;
-- theme choice is per-user via settings_json.theme_id and syncs across devices).
-- True-black background for OLED; Maize (#FFCB05) primary; a readable Michigan
-- blue accent; dark-blue surfaces so cards read subtly blue against the black.
-- on-primary / on-* foregrounds are auto-derived by WCAG contrast, so the light
-- Maize primary gets dark button text automatically. warning is amber (distinct
-- from the maize primary). Token contract per frontend lib/themeTokens.ts.

-- Idempotent guard (the unique constraint is on (slug, owner_id), and NULL
-- owner_ids don't collide, so a plain ON CONFLICT wouldn't dedupe).
INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT
    'Michigan — Maize & Blue (OLED)',
    'michigan-oled',
    true,
    NULL,
    '{
        "background": "#000000",
        "surface": "#0a1626",
        "primary": "#ffcb05",
        "accent": "#4b8fe2",
        "text": "#f3f4f6",
        "text_muted": "#94a3b8",
        "border": "#1c2c44",
        "danger": "#ff5d57",
        "success": "#34d399",
        "warning": "#f59e0b",
        "error": "#ff5d57"
    }'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes WHERE slug = 'michigan-oled' AND owner_id IS NULL
);
