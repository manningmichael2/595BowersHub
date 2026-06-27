-- 0044 — darken the indigo primary to clear WCAG AA on-primary contrast (R1.3).
--
-- Dark Navy and OLED Black used indigo-500 (#6366f1) as `primary`. The readable
-- foreground over it tops out at 4.70:1 (black) / 4.47:1 (white) — white text,
-- the conventional look for an indigo button, misses the 4.5:1 AA-normal bar,
-- and max-contrast would otherwise force BLACK label text (off-looking).
--
-- Nudging primary to indigo-600 (#4f46e5) lifts white-on-primary to 6.29:1, so
-- the derived `--color-on-primary` becomes white (conventional) AND clears AA
-- with margin. A subtle, slightly deeper indigo; only these two presets used
-- #6366f1 as primary. Forward-only, is_preset-scoped.

UPDATE public.bh_themes
SET tokens_json = tokens_json || '{"primary": "#4f46e5"}'::jsonb,
    updated_at = now()
WHERE is_preset = true
  AND slug IN ('dark-navy', 'oled-black')
  AND tokens_json->>'primary' = '#6366f1';
