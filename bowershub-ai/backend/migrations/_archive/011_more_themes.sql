-- ============================================================
-- BowersHub AI: Additional preset themes
-- Adds 6 new presets to public.bh_themes:
--   - Michigan (Maize & Blue dark, the user's alma-mater colors)
--   - OLED Black (true #000000 background for OLED displays)
--   - Dracula (the popular dev-tool palette)
--   - Nord (cool arctic palette)
--   - Solarized Dark (classic Ethan Schoonover palette)
--   - Sunset (warm purple→orange dusk palette)
--
-- Token shape matches design.md: background, surface, primary, accent,
-- text, text_muted, border, danger, success. All values 6-digit hex.
-- Each insert is guarded with NOT EXISTS so re-running the migration
-- won't create duplicates.
-- ============================================================

-- ---------- Michigan (Maize & Blue) -----------------------------------
-- Official UM colors: Maize #FFCB05, Blue #00274C. The background goes
-- a step darker than UM Blue so the chrome contrasts the surface.

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Michigan', 'michigan', true, NULL, '{
    "background":  "#00132e",
    "surface":     "#00274c",
    "primary":     "#ffcb05",
    "accent":      "#ffd75e",
    "text":        "#f8f0d8",
    "text_muted":  "#a3b1c7",
    "border":      "#1b3a66",
    "danger":      "#ef4444",
    "success":     "#4ade80"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'michigan' AND owner_id IS NULL
);

-- ---------- OLED Black ------------------------------------------------
-- Pure #000000 background to take full advantage of OLED pixel-off
-- power savings. Surface is a hair above black so panels are still
-- distinguishable. Indigo primary keeps the app's existing brand feel.

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'OLED Black', 'oled-black', true, NULL, '{
    "background":  "#000000",
    "surface":     "#0a0a0a",
    "primary":     "#6366f1",
    "accent":      "#818cf8",
    "text":        "#fafafa",
    "text_muted":  "#a1a1aa",
    "border":      "#18181b",
    "danger":      "#ef4444",
    "success":     "#22c55e"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'oled-black' AND owner_id IS NULL
);

-- ---------- Dracula ---------------------------------------------------
-- Official Dracula theme palette (https://draculatheme.com).

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Dracula', 'dracula', true, NULL, '{
    "background":  "#282a36",
    "surface":     "#343746",
    "primary":     "#bd93f9",
    "accent":      "#ff79c6",
    "text":        "#f8f8f2",
    "text_muted":  "#6272a4",
    "border":      "#44475a",
    "danger":      "#ff5555",
    "success":     "#50fa7b"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'dracula' AND owner_id IS NULL
);

-- ---------- Nord ------------------------------------------------------
-- Official Nord palette (https://www.nordtheme.com). nord0..nord14.

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Nord', 'nord', true, NULL, '{
    "background":  "#2e3440",
    "surface":     "#3b4252",
    "primary":     "#88c0d0",
    "accent":      "#81a1c1",
    "text":        "#eceff4",
    "text_muted":  "#d8dee9",
    "border":      "#4c566a",
    "danger":      "#bf616a",
    "success":     "#a3be8c"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'nord' AND owner_id IS NULL
);

-- ---------- Solarized Dark --------------------------------------------
-- Ethan Schoonover's classic palette. base03 background, base02 surface,
-- base1 for primary text (slightly brighter than the strict base0 spec
-- so chat content reads comfortably on modern displays).

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Solarized Dark', 'solarized-dark', true, NULL, '{
    "background":  "#002b36",
    "surface":     "#073642",
    "primary":     "#268bd2",
    "accent":      "#2aa198",
    "text":        "#93a1a1",
    "text_muted":  "#586e75",
    "border":      "#094352",
    "danger":      "#dc322f",
    "success":     "#859900"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'solarized-dark' AND owner_id IS NULL
);

-- ---------- Sunset ----------------------------------------------------
-- Warm dusk palette: deep plum background, orange primary, pink accent.

INSERT INTO public.bh_themes (name, slug, is_preset, owner_id, tokens_json)
SELECT 'Sunset', 'sunset', true, NULL, '{
    "background":  "#1a0e1f",
    "surface":     "#2a1830",
    "primary":     "#f97316",
    "accent":      "#ec4899",
    "text":        "#fef3e2",
    "text_muted":  "#c4a3b0",
    "border":      "#4a2c54",
    "danger":      "#ef4444",
    "success":     "#facc15"
}'::jsonb
WHERE NOT EXISTS (
    SELECT 1 FROM public.bh_themes
    WHERE slug = 'sunset' AND owner_id IS NULL
);
