-- 0043 — promote `warning` and `error` to real per-theme tokens (R1.2).
--
-- Before this, `--color-warning` / `--color-error` existed ONLY as index.css
-- first-paint defaults: App.tsx never injected them and no preset's tokens_json
-- carried them, so switching themes left them frozen at the Dark Navy default
-- (they failed the "no frozen-palette" criterion). The token contract now
-- requires all 11 keys; this backfills the two missing ones into every preset.
--
-- Forward-only, additive jsonb merge. `error` is set to each theme's own
-- `danger` red (keeping error/danger visually aligned); `warning` is a
-- theme-appropriate amber/yellow — using each palette's native yellow where it
-- has one (Dracula #f1fa8c, Nord #ebcb8b, Solarized #b58900), a darker amber for
-- the light theme (contrast on white), and the default amber otherwise.
--
-- Scoped to is_preset = true so a user's custom theme is never overwritten;
-- custom themes that lack these keys are filled at runtime by
-- normalizeThemeTokens (frontend). The full-opacity resolved colors of every
-- OTHER token are unchanged. Back up bh_themes before applying in production.

WITH preset_tokens(slug, warning, error) AS (
    VALUES
        ('dark-navy',      '#eab308', '#ef4444'),
        ('light-stone',    '#d97706', '#dc2626'),
        ('forest',         '#eab308', '#ef4444'),
        ('michigan',       '#f59e0b', '#ef4444'),
        ('oled-black',     '#eab308', '#ef4444'),
        ('dracula',        '#f1fa8c', '#ff5555'),
        ('nord',           '#ebcb8b', '#bf616a'),
        ('solarized-dark', '#b58900', '#dc322f'),
        ('sunset',         '#facc15', '#ef4444'),
        ('mono',           '#eab308', '#ef4444')
)
UPDATE public.bh_themes t
SET tokens_json = t.tokens_json || jsonb_build_object('warning', p.warning, 'error', p.error),
    updated_at = now()
FROM preset_tokens p
WHERE t.slug = p.slug
  AND t.is_preset = true;
