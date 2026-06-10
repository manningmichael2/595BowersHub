/**
 * Property-based tests for FractionField round-trip conversion.
 *
 * **Validates: Requirements 8.3**
 *
 * The FractionField stores decimals in the DB and displays them as fractions
 * (e.g., 0.375 → "3/8"). These tests verify the round-trip property:
 * decimal → display string → parse back to decimal should produce the original value.
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { decimalToFraction, fractionToDecimal } from '../fields'

/** Valid denominators for woodworking fractions */
const VALID_DENOMINATORS = [2, 4, 8, 16, 32, 64] as const

describe('FractionField round-trip conversion', () => {
  it('Property 7a: Round-trip for valid fractions (n/d where d ∈ {2,4,8,16,32,64})', () => {
    // Generate fractions as numerator/denominator pairs where 0 < n < d
    const fractionArb = fc.oneof(
      ...VALID_DENOMINATORS.map((denom) =>
        fc.integer({ min: 1, max: denom - 1 }).map((num) => ({
          num,
          denom,
          decimal: num / denom,
        }))
      )
    )

    fc.assert(
      fc.property(fractionArb, ({ decimal }) => {
        const displayed = decimalToFraction(decimal)
        const parsed = fractionToDecimal(displayed)
        expect(parsed).not.toBeNull()
        expect(parsed).toBeCloseTo(decimal, 10)
      }),
      { numRuns: 500 }
    )
  })

  it('Property 7b: Round-trip for whole numbers', () => {
    fc.assert(
      fc.property(fc.integer({ min: 0, max: 10000 }), (n) => {
        const displayed = decimalToFraction(n)
        const parsed = fractionToDecimal(displayed)
        expect(parsed).not.toBeNull()
        expect(parsed).toBe(n)
      }),
      { numRuns: 200 }
    )
  })

  it('Property 7c: Round-trip for mixed numbers (whole + fraction)', () => {
    const mixedArb = fc.tuple(
      fc.integer({ min: 1, max: 500 }),
      fc.oneof(
        ...VALID_DENOMINATORS.map((denom) =>
          fc.integer({ min: 1, max: denom - 1 }).map((num) => ({
            num,
            denom,
            fractional: num / denom,
          }))
        )
      )
    ).map(([whole, frac]) => ({
      whole,
      ...frac,
      decimal: whole + frac.fractional,
    }))

    fc.assert(
      fc.property(mixedArb, ({ decimal }) => {
        const displayed = decimalToFraction(decimal)
        const parsed = fractionToDecimal(displayed)
        expect(parsed).not.toBeNull()
        expect(parsed).toBeCloseTo(decimal, 10)
      }),
      { numRuns: 500 }
    )
  })

  it('Property 7d: Parse accepts various formats for the same value', () => {
    // For any valid fraction, all equivalent string representations parse to the same decimal
    const fractionArb = fc.oneof(
      ...VALID_DENOMINATORS.map((denom) =>
        fc.integer({ min: 1, max: denom - 1 }).map((num) => ({
          num,
          denom,
          decimal: num / denom,
        }))
      )
    )

    fc.assert(
      fc.property(fractionArb, ({ num, denom, decimal }) => {
        // All these formats should parse to the same value
        const fractionStr = `${num}/${denom}`
        const fractionWithQuote = `${num}/${denom}"`
        const decimalStr = String(decimal)

        const fromFraction = fractionToDecimal(fractionStr)
        const fromQuoted = fractionToDecimal(fractionWithQuote)
        const fromDecimal = fractionToDecimal(decimalStr)

        expect(fromFraction).toBeCloseTo(decimal, 10)
        expect(fromQuoted).toBeCloseTo(decimal, 10)
        expect(fromDecimal).toBeCloseTo(decimal, 10)
      }),
      { numRuns: 200 }
    )
  })

  it('Property 7e: Null/empty handling', () => {
    // decimalToFraction(null) returns ''
    expect(decimalToFraction(null)).toBe('')
    // decimalToFraction(undefined) returns ''
    expect(decimalToFraction(undefined)).toBe('')
    // fractionToDecimal('') returns null
    expect(fractionToDecimal('')).toBeNull()
    // fractionToDecimal with whitespace returns null
    expect(fractionToDecimal('   ')).toBeNull()
  })
})
