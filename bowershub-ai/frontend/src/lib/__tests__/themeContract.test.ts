import { describe, it, expect } from 'vitest'
import {
  REQUIRED_TOKEN_KEYS,
  normalizeThemeTokens,
  FOREGROUND_COMPUTED_ALIASES,
  TOKEN_FALLBACKS,
} from '../themeTokens'
import { readableForeground, contrastRatio } from '../contrast'

/**
 * The 10 seeded presets (bh_themes), including the warning/error values added
 * by migration 0043. Kept in sync with backend/migrations/0001_baseline.sql +
 * 0043_theme_warning_error_tokens.sql. Used to prove the token contract and the
 * foreground aliases hold across every shipped theme (R1.2, R1.3, R2.7).
 */
const PRESETS: Record<string, Record<string, string>> = {
  'dark-navy': { background: '#0f0f1a', surface: '#1a1a2e', primary: '#4f46e5', accent: '#818cf8', text: '#e5e7eb', text_muted: '#94a3b8', border: '#374151', danger: '#ef4444', success: '#22c55e', warning: '#eab308', error: '#ef4444' },
  'light-stone': { background: '#f8f7f4', surface: '#ffffff', primary: '#4f46e5', accent: '#6366f1', text: '#1f2937', text_muted: '#6b7280', border: '#e5e7eb', danger: '#dc2626', success: '#16a34a', warning: '#d97706', error: '#dc2626' },
  forest: { background: '#0f1f17', surface: '#1a2e22', primary: '#22c55e', accent: '#4ade80', text: '#e5f7ec', text_muted: '#94a3b8', border: '#2d3f33', danger: '#ef4444', success: '#22c55e', warning: '#eab308', error: '#ef4444' },
  michigan: { background: '#00132e', surface: '#00274c', primary: '#ffcb05', accent: '#ffd75e', text: '#f8f0d8', text_muted: '#a3b1c7', border: '#1b3a66', danger: '#ef4444', success: '#4ade80', warning: '#f59e0b', error: '#ef4444' },
  'oled-black': { background: '#000000', surface: '#0a0a0a', primary: '#4f46e5', accent: '#818cf8', text: '#fafafa', text_muted: '#a1a1aa', border: '#18181b', danger: '#ef4444', success: '#22c55e', warning: '#eab308', error: '#ef4444' },
  dracula: { background: '#282a36', surface: '#343746', primary: '#bd93f9', accent: '#ff79c6', text: '#f8f8f2', text_muted: '#6272a4', border: '#44475a', danger: '#ff5555', success: '#50fa7b', warning: '#f1fa8c', error: '#ff5555' },
  nord: { background: '#2e3440', surface: '#3b4252', primary: '#88c0d0', accent: '#81a1c1', text: '#eceff4', text_muted: '#d8dee9', border: '#4c566a', danger: '#bf616a', success: '#a3be8c', warning: '#ebcb8b', error: '#bf616a' },
  'solarized-dark': { background: '#002b36', surface: '#073642', primary: '#268bd2', accent: '#2aa198', text: '#93a1a1', text_muted: '#586e75', border: '#094352', danger: '#dc322f', success: '#859900', warning: '#b58900', error: '#dc322f' },
  sunset: { background: '#1a0e1f', surface: '#2a1830', primary: '#f97316', accent: '#ec4899', text: '#fef3e2', text_muted: '#c4a3b0', border: '#4a2c54', danger: '#ef4444', success: '#facc15', warning: '#facc15', error: '#ef4444' },
  mono: { background: '#000000', surface: '#1a1a1a', primary: '#ffffff', accent: '#d1d5db', text: '#e5e7eb', text_muted: '#9ca3af', border: '#374151', danger: '#ef4444', success: '#22c55e', warning: '#eab308', error: '#ef4444' },
}

describe('token contract (R1.2)', () => {
  it('every preset resolves all 11 required keys after normalize', () => {
    for (const [slug, tokens] of Object.entries(PRESETS)) {
      const norm = normalizeThemeTokens(tokens)
      for (const key of REQUIRED_TOKEN_KEYS) {
        expect(norm[key], `${slug}.${key}`).toBeTypeOf('string')
        expect(norm[key].length, `${slug}.${key} non-empty`).toBeGreaterThan(0)
      }
    }
  })

  it('fills a missing key from the deterministic fallback (no undefined)', () => {
    const norm = normalizeThemeTokens({ primary: '#123456' })
    expect(norm.primary).toBe('#123456') // preserved
    expect(norm.warning).toBe(TOKEN_FALLBACKS.warning) // filled
    expect(norm.background).toBe(TOKEN_FALLBACKS.background) // filled
    for (const key of REQUIRED_TOKEN_KEYS) expect(norm[key]).toBeTruthy()
  })

  it('error falls back to the theme’s own danger when error is absent', () => {
    const norm = normalizeThemeTokens({ danger: '#abcdef' })
    expect(norm.error).toBe('#abcdef')
  })

  it('does not override values the theme already provides', () => {
    const full = normalizeThemeTokens(PRESETS['dracula'])
    expect(full.warning).toBe('#f1fa8c')
    expect(full.error).toBe('#ff5555')
  })
})

describe('foreground aliases meet WCAG AA across all 10 presets (R1.3, R2.7)', () => {
  for (const [slug, tokens] of Object.entries(PRESETS)) {
    it(`${slug}: every computed on-* alias has ≥ 4.5:1 contrast`, () => {
      for (const tokenKey of Object.values(FOREGROUND_COMPUTED_ALIASES)) {
        const bg = tokens[tokenKey]
        const fg = readableForeground(bg)
        const ratio = contrastRatio(fg, bg)
        expect(ratio, `${slug} on-${tokenKey} (${fg} on ${bg})`).toBeGreaterThanOrEqual(4.5)
      }
    })
  }

  it('on-primary is white over the indigo-600 primary (migration 0044 — conventional look, AA-clean)', () => {
    for (const slug of ['dark-navy', 'oled-black']) {
      expect(PRESETS[slug].primary).toBe('#4f46e5')
      expect(readableForeground(PRESETS[slug].primary)).toBe('#ffffff')
    }
  })
})
