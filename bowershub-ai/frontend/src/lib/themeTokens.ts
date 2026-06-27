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
 * The token contract (R1.2): the color keys a theme MUST resolve. This is the
 * explicit, enumerated set that replaces the old free-form
 * `z.record(string,string)` — a primitive can rely on every one of these
 * resolving to a real color, never `undefined`/transparent.
 *
 * `text_muted` is the one underscore key (it injects as `--color-text-muted`).
 * `warning` and `error` were frozen defects before this contract: they lived
 * only as `index.css` defaults and were never injected per-theme, so a theme
 * switch left them stuck. They are now first-class tokens.
 */
export const REQUIRED_TOKEN_KEYS = [
  'background',
  'surface',
  'primary',
  'accent',
  'text',
  'text_muted',
  'border',
  'danger',
  'success',
  'warning',
  'error',
] as const

export type RequiredTokenKey = (typeof REQUIRED_TOKEN_KEYS)[number]

/**
 * Deterministic fallbacks (Dark Navy preset) used to fill any missing token so
 * the contract holds even for themes authored before a key existed (e.g. custom
 * themes without `warning`/`error`). `error` falls back to the theme's own
 * `danger` when present, else this red — keeping error/danger visually aligned.
 */
export const TOKEN_FALLBACKS: Record<RequiredTokenKey, string> = {
  background: '#0f0f1a',
  surface: '#1a1a2e',
  primary: '#6366f1',
  accent: '#818cf8',
  text: '#e5e7eb',
  text_muted: '#94a3b8',
  border: '#374151',
  danger: '#ef4444',
  success: '#22c55e',
  warning: '#eab308',
  error: '#ef4444',
}

/**
 * Return a complete token set: every `REQUIRED_TOKEN_KEYS` entry resolved to a
 * real hex string, filling gaps from `TOKEN_FALLBACKS` (and `error`→`danger`).
 * Extra keys on the input are preserved. This is the runtime half of the R1.2
 * contract — paired with the Zod schema's compile-time detection.
 */
export function normalizeThemeTokens(
  raw: Record<string, string | undefined> | null | undefined,
): Record<string, string> {
  const out: Record<string, string> = { ...(raw ?? {}) } as Record<string, string>
  for (const key of REQUIRED_TOKEN_KEYS) {
    const v = out[key]
    if (typeof v !== 'string' || v.length === 0) {
      out[key] = key === 'error' ? out.danger ?? TOKEN_FALLBACKS.error : TOKEN_FALLBACKS[key]
    }
  }
  return out
}

/**
 * Foreground aliases (R1.3) — a readable text/icon color for each surface,
 * exposed as `--color-on-<name>`. Two kinds:
 *   - `text`-based: aliases that simply reuse an existing text token (the
 *     foreground for neutral surfaces is the theme's text color).
 *   - `computed`: aliases over a *colored* token, where the readable foreground
 *     is chosen by max WCAG contrast (see `readableForeground`).
 * These are derived from existing tokens — no new theme authority (R1.1).
 */
export const FOREGROUND_TEXT_ALIASES: Record<string, RequiredTokenKey> = {
  '--color-on-background': 'text',
  '--color-on-surface': 'text',
  '--color-on-muted': 'text',
}
export const FOREGROUND_COMPUTED_ALIASES: Record<string, RequiredTokenKey> = {
  '--color-on-primary': 'primary',
  '--color-on-accent': 'accent',
  '--color-on-danger': 'danger',
  '--color-on-success': 'success',
  '--color-on-warning': 'warning',
  '--color-on-error': 'error',
}

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
