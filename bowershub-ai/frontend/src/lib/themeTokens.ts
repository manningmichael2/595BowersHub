/**
 * Theme-token helpers shared by `App.tsx` (runtime injection) and tests.
 *
 * The DB (`bh_themes.tokens_json`) stores each color as **hex** — that stays
 * the single source of truth and keeps the ThemeBuilder hex pickers and the
 * on-primary luminance math working. At injection time we set TWO CSS custom
 * properties per token on `:root`:
 *
 *   --color-<name>       the full color value (hex), consumed directly by the
 *                        many existing inline `style={{ … 'var(--color-…)' }}`
 *                        usages and by the `index.css` rules.
 *   --color-<name>-rgb   a DERIVED `"R G B"` channel triple, consumed only by
 *                        the Tailwind color utilities — `tailwind.config.ts`
 *                        maps every color to `rgb(var(--color-<name>-rgb) /
 *                        <alpha-value>)` so opacity modifiers like
 *                        `bg-primary/20` compose alpha correctly (Tailwind v3
 *                        cannot compose alpha against a hex-valued var).
 *
 * The triple is derived from the same hex — it is a second *representation*,
 * not a second source of authority (satisfies R1.1). This mirrors how
 * `--color-on-primary` and `--color-surface-light/dark` are already derived
 * in `App.tsx`. Full-opacity colors are unchanged: `rgb(99 102 241 / 1)` ===
 * `#6366f1`.
 */

/** The `--color-<name>-rgb` suffix used for the alpha-composable triple var. */
export const RGB_VAR_SUFFIX = '-rgb'

/**
 * Convert a hex color (`#6366f1`, `6366f1`, `#fff`, `fff`) to a Tailwind
 * alpha-composable space-separated channel triple (`"99 102 241"`).
 * Returns `null` for values that are not parseable hex (e.g. already a
 * keyword/rgb string), so callers can skip setting the `-rgb` var rather
 * than emit an invalid one.
 */
export function hexToTriple(hex: string): string | null {
  if (typeof hex !== 'string') return null
  let h = hex.trim().replace(/^#/, '')
  // Expand 3-digit shorthand (#abc → #aabbcc).
  if (h.length === 3) {
    h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]
  }
  if (h.length !== 6 || !/^[0-9a-fA-F]{6}$/.test(h)) return null
  const r = parseInt(h.slice(0, 2), 16)
  const g = parseInt(h.slice(2, 4), 16)
  const b = parseInt(h.slice(4, 6), 16)
  return `${r} ${g} ${b}`
}

/**
 * Set both the full-color var and its derived `-rgb` triple var on an element.
 * No-op for the triple if the value isn't parseable hex (the full-color var is
 * still set, so direct consumers keep working).
 */
export function setColorVar(
  el: { style: { setProperty(name: string, value: string): void } },
  cssVar: string,
  value: string,
): void {
  el.style.setProperty(cssVar, value)
  const triple = hexToTriple(value)
  if (triple) el.style.setProperty(`${cssVar}${RGB_VAR_SUFFIX}`, triple)
}
