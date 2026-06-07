/**
 * Property-based tests for `lib/contrast.ts` — the frontend mirror of
 * `backend/services/theme_validator.py`.
 *
 * These tests use fast-check to generate hex color pairs and assert that
 * the TypeScript helper agrees with a reference implementation written
 * inline in this file (a literal port of the Python WCAG math + the same
 * `block`/`warn`/`ok` thresholds). They also assert symmetry of the
 * decision under argument swap, which the live ThemeBuilder UI relies on
 * (the badge must not flicker when the user switches which token is
 * "text" vs "background").
 *
 * Property 3 (frontend mirror): contrast decision matches backend
 * Validates: Requirements R1.7, R1.8
 *
 * Iterations: 200 per property (above the 100-iteration floor in the
 * design doc).
 */

import { describe, it, expect } from 'vitest'
import fc from 'fast-check'

import {
  contrastDecision,
  contrastRatio,
  isValidHex,
  relativeLuminance,
} from '../contrast'

// --- Reference implementation -------------------------------------------------
//
// Independently coded port of the WCAG 2.x relative-luminance + contrast-ratio
// formulas, plus the same threshold table the backend uses. Kept inline (not
// imported from contrast.ts) so a regression in contrast.ts cannot silently
// pass through here.
//
// Thresholds (from theme_validator.py):
//   ratio < 2.0     → "block"
//   2.0 <= r < 4.5  → "warn"
//   ratio >= 4.5    → "ok"

const REF_BLOCK = 2.0
const REF_OK = 4.5

function refHexToRgb(hex: string): [number, number, number] {
  const s = hex.replace(/^#/, '').slice(0, 6)
  return [
    parseInt(s.slice(0, 2), 16),
    parseInt(s.slice(2, 4), 16),
    parseInt(s.slice(4, 6), 16),
  ]
}

function refChannel(byte: number): number {
  const c = byte / 255
  return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
}

function refLuminance(hex: string): number {
  const [r, g, b] = refHexToRgb(hex)
  return 0.2126 * refChannel(r) + 0.7152 * refChannel(g) + 0.0722 * refChannel(b)
}

function refRatio(a: string, b: string): number {
  const la = refLuminance(a)
  const lb = refLuminance(b)
  const lighter = Math.max(la, lb)
  const darker = Math.min(la, lb)
  return (lighter + 0.05) / (darker + 0.05)
}

function refDecision(text: string, bg: string): 'ok' | 'warn' | 'block' {
  const r = refRatio(text, bg)
  if (r < REF_BLOCK) return 'block'
  if (r < REF_OK) return 'warn'
  return 'ok'
}

// --- Generators ---------------------------------------------------------------
//
// `hexColorArb` produces strings that satisfy `^#?[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$`
// with the leading `#` and an optional trailing alpha pair both varied so we
// exercise every accepted shape (R1.6 grammar). Mixed case is included by
// fast-check's `hexa` generator.

const hexCharArb = fc.constantFrom(...'0123456789abcdefABCDEF'.split(''))

const hex2Arb = fc
  .tuple(hexCharArb, hexCharArb)
  .map(([a, b]) => a + b)

const hexColorArb: fc.Arbitrary<string> = fc
  .tuple(
    fc.constantFrom('', '#'),
    hex2Arb,
    hex2Arb,
    hex2Arb,
    fc.option(hex2Arb, { nil: '' }),
  )
  .map(([prefix, r, g, bl, alpha]) => `${prefix}${r}${g}${bl}${alpha ?? ''}`)

// --- Tests --------------------------------------------------------------------

describe('contrast helper — property tests', () => {
  it('Property 3a: contrastDecision matches the reference implementation', () => {
    fc.assert(
      fc.property(hexColorArb, hexColorArb, (text, bg) => {
        // Sanity: every value our generator produces must pass isValidHex,
        // otherwise the rest of the assertions are testing the wrong path.
        expect(isValidHex(text)).toBe(true)
        expect(isValidHex(bg)).toBe(true)

        const got = contrastDecision(text, bg)
        const want = refDecision(text, bg)
        expect(got).toBe(want)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 3b: contrastDecision is symmetric under argument swap', () => {
    fc.assert(
      fc.property(hexColorArb, hexColorArb, (a, b) => {
        // R1.7/R1.8: the decision is a function of the contrast ratio,
        // which is itself symmetric in (text, bg). Swapping arguments
        // must not change `ok`/`warn`/`block`. The ThemeBuilder UI
        // relies on this so the badge does not flicker as the user
        // edits which token is "text" vs "background".
        expect(contrastDecision(a, b)).toBe(contrastDecision(b, a))
      }),
      { numRuns: 200 },
    )
  })

  it('Property 3c: contrastRatio is symmetric and within [1.0, 21.0]', () => {
    // Cross-check on the underlying ratio so a bug in the threshold
    // boundaries cannot mask a bug in the ratio itself.
    fc.assert(
      fc.property(hexColorArb, hexColorArb, (a, b) => {
        const ab = contrastRatio(a, b)
        const ba = contrastRatio(b, a)
        // Symmetric to within floating-point noise.
        expect(Math.abs(ab - ba)).toBeLessThan(1e-9)
        // WCAG ratio is bounded.
        expect(ab).toBeGreaterThanOrEqual(1 - 1e-9)
        expect(ab).toBeLessThanOrEqual(21 + 1e-9)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 3d: relativeLuminance lies in [0, 1] for any valid hex', () => {
    fc.assert(
      fc.property(hexColorArb, (h) => {
        const l = relativeLuminance(h)
        expect(l).toBeGreaterThanOrEqual(0)
        expect(l).toBeLessThanOrEqual(1)
      }),
      { numRuns: 200 },
    )
  })

  it('Property 3e: identical text and background always blocks', () => {
    // Same color on same color → ratio 1.0 → "block". This is a
    // tightening of R1.7 ("ratio < 2.0 → block") and a useful sanity
    // check that the threshold side of the helper is wired correctly.
    fc.assert(
      fc.property(hexColorArb, (h) => {
        expect(contrastDecision(h, h)).toBe('block')
      }),
      { numRuns: 200 },
    )
  })
})
