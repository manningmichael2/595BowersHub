/**
 * contrast — pure helpers mirroring `backend/services/theme_validator.py`.
 *
 * Used by the personal theme builder (`<ThemeBuilder>`) to surface a live
 * `ok` / `warn` / `block` badge while the user picks colors so they don't
 * have to round-trip to the server to learn that text/background contrast
 * is unreadable.
 *
 * The math here MUST agree with the backend so a theme that passes the
 * client check also passes the server-side `theme_validator.contrast_decision`
 * check on save. Property test in `__tests__/contrast.property.test.ts`
 * cross-checks this.
 *
 * References:
 *   - WCAG 2.x relative luminance:
 *     https://www.w3.org/WAI/GL/wiki/Relative_luminance
 *   - WCAG contrast ratio:
 *     https://www.w3.org/TR/WCAG21/#dfn-contrast-ratio
 *
 * _Requirements: R1.6, R1.7, R1.8
 */

// Acceptable hex grammar — same as backend `_HEX_RE`. Optional leading `#`,
// then exactly 6 hex digits, with an optional 2 trailing hex digits (alpha).
// Mixed case allowed.
const HEX_RE = /^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/

// WCAG thresholds — same constants as backend `_CONTRAST_BLOCK` / `_CONTRAST_OK`.
const CONTRAST_BLOCK = 2.0
const CONTRAST_OK = 4.5

export type ContrastDecision = 'ok' | 'warn' | 'block'

/**
 * Returns true iff `s` matches `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`.
 *
 * Total over all input types: non-strings (null, undefined, number, ...)
 * return false rather than throw.
 */
export function isValidHex(s: unknown): s is string {
  if (typeof s !== 'string') return false
  return HEX_RE.test(s)
}

/** Parse a validated hex string into [r, g, b] 0..255. Drops alpha if present. */
function hexToRgb(hex: string): [number, number, number] {
  const s = hex.replace(/^#/, '').slice(0, 6)
  return [
    parseInt(s.slice(0, 2), 16),
    parseInt(s.slice(2, 4), 16),
    parseInt(s.slice(4, 6), 16),
  ]
}

/** Linearize a single 0..255 sRGB channel per the WCAG spec. */
function channelLuminance(byte: number): number {
  const c = byte / 255
  if (c <= 0.03928) return c / 12.92
  return Math.pow((c + 0.055) / 1.055, 2.4)
}

/**
 * WCAG relative luminance for an sRGB color, in [0, 1].
 *
 * Throws if `hex` is not a valid hex token. Alpha (if present) is ignored.
 */
export function relativeLuminance(hex: string): number {
  if (!isValidHex(hex)) {
    throw new Error(`not a valid hex color: ${String(hex)}`)
  }
  const [r, g, b] = hexToRgb(hex)
  return (
    0.2126 * channelLuminance(r) +
    0.7152 * channelLuminance(g) +
    0.0722 * channelLuminance(b)
  )
}

/**
 * WCAG contrast ratio between two colors. Result is symmetric in its
 * arguments — `contrastRatio(a, b) === contrastRatio(b, a)`.
 *
 * Returns a float in [1, 21]. Higher is more readable. Throws on invalid input.
 */
export function contrastRatio(textHex: string, bgHex: string): number {
  const l1 = relativeLuminance(textHex)
  const l2 = relativeLuminance(bgHex)
  const lighter = Math.max(l1, l2)
  const darker = Math.min(l1, l2)
  return (lighter + 0.05) / (darker + 0.05)
}

/**
 * Map a contrast ratio to a save-time policy:
 *   - ratio < 2.0     → "block"  (refuse save; unreadable)
 *   - 2.0 <= r < 4.5  → "warn"   (allow save with warning)
 *   - ratio >= 4.5    → "ok"     (allow save silently)
 *
 * Mirrors `theme_validator.contrast_decision` (R1.7, R1.8).
 *
 * Returns 'block' if either input fails hex validation, so the UI never
 * lets a malformed token through.
 */
export function contrastDecision(textHex: string, bgHex: string): ContrastDecision {
  if (!isValidHex(textHex) || !isValidHex(bgHex)) return 'block'
  const ratio = contrastRatio(textHex, bgHex)
  if (ratio < CONTRAST_BLOCK) return 'block'
  if (ratio < CONTRAST_OK) return 'warn'
  return 'ok'
}

/**
 * Normalize a hex value entered by the user: prepend `#`, lowercase.
 * Pass-through if invalid (caller checks separately via `isValidHex`).
 */
export function normalizeHex(input: string): string {
  if (typeof input !== 'string') return input
  const trimmed = input.trim()
  if (trimmed.length === 0) return trimmed
  const withHash = trimmed.startsWith('#') ? trimmed : `#${trimmed}`
  return withHash.toLowerCase()
}
