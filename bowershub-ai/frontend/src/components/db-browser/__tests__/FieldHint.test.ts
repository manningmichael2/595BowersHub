/**
 * Property-based tests for FieldHint JSON serialization round-trip.
 *
 * **Validates: Requirements 18.4, 18.5**
 *
 * Property 12: Field hint round-trip
 * - Tests that any valid FieldHint object survives JSON.parse(JSON.stringify(hint))
 *   without data loss.
 * - Tests that input_type is always one of the valid enum values.
 * - Tests that options is either null or a string array.
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import type { FieldHint } from '../../../stores/db-browser'

// ---- Arbitraries ----------------------------------------------------------

/** Valid FieldHint input_type values */
const validInputTypes = [
  'text', 'number', 'fraction', 'select', 'url', 'date', 'boolean', 'textarea',
] as const

/** Arbitrary for a FieldHint input_type */
const arbInputType = fc.constantFrom(...validInputTypes)

/**
 * Bounded finite double, normalizing -0 to 0. JSON.stringify(-0) === "0", so
 * a raw -0 from the generator can't survive a round-trip and would fail the
 * deep-equality property for a reason that has nothing to do with FieldHint.
 */
const arbBoundedDouble = (min: number, max: number) =>
  fc
    .double({ min, max, noNaN: true, noDefaultInfinity: true })
    .map(v => (Object.is(v, -0) ? 0 : v))

/** Arbitrary for a FieldHint object */
const arbFieldHint: fc.Arbitrary<FieldHint> = fc.record({
  column_name: fc.string({ minLength: 1, maxLength: 63 }),
  input_type: arbInputType,
  options: fc.oneof(fc.constant(null), fc.array(fc.string({ maxLength: 100 }), { minLength: 1, maxLength: 20 })),
  prefix: fc.oneof(fc.constant(null), fc.string({ maxLength: 20 })),
  suffix: fc.oneof(fc.constant(null), fc.string({ maxLength: 20 })),
  min_val: fc.oneof(fc.constant(null), arbBoundedDouble(-1e6, 1e6)),
  max_val: fc.oneof(fc.constant(null), arbBoundedDouble(-1e6, 1e6)),
  step: fc.oneof(fc.constant(null), arbBoundedDouble(0.001, 1000)),
  placeholder: fc.oneof(fc.constant(null), fc.string({ maxLength: 100 })),
})

// ---- Property 12: Field hint round-trip -----------------------------------

describe('Property 12: Field hint round-trip', () => {
  it('JSON serialization round-trip preserves all FieldHint fields', () => {
    fc.assert(
      fc.property(arbFieldHint, (hint) => {
        const serialized = JSON.stringify(hint)
        const deserialized: FieldHint = JSON.parse(serialized)

        expect(deserialized.column_name).toBe(hint.column_name)
        expect(deserialized.input_type).toBe(hint.input_type)
        expect(deserialized.options).toEqual(hint.options)
        expect(deserialized.prefix).toBe(hint.prefix)
        expect(deserialized.suffix).toBe(hint.suffix)
        expect(deserialized.min_val).toBe(hint.min_val)
        expect(deserialized.max_val).toBe(hint.max_val)
        expect(deserialized.step).toBe(hint.step)
        expect(deserialized.placeholder).toBe(hint.placeholder)
      }),
      { numRuns: 500 }
    )
  })

  it('input_type is always one of the valid enum values after round-trip', () => {
    fc.assert(
      fc.property(arbFieldHint, (hint) => {
        const deserialized: FieldHint = JSON.parse(JSON.stringify(hint))
        expect(validInputTypes).toContain(deserialized.input_type)
      }),
      { numRuns: 500 }
    )
  })

  it('options is either null or a string array after round-trip', () => {
    fc.assert(
      fc.property(arbFieldHint, (hint) => {
        const deserialized: FieldHint = JSON.parse(JSON.stringify(hint))

        if (deserialized.options === null) {
          expect(deserialized.options).toBeNull()
        } else {
          expect(Array.isArray(deserialized.options)).toBe(true)
          for (const opt of deserialized.options) {
            expect(typeof opt).toBe('string')
          }
        }
      }),
      { numRuns: 500 }
    )
  })

  it('deep equality holds between original and round-tripped hint', () => {
    fc.assert(
      fc.property(arbFieldHint, (hint) => {
        const roundTripped: FieldHint = JSON.parse(JSON.stringify(hint))
        expect(roundTripped).toEqual(hint)
      }),
      { numRuns: 500 }
    )
  })
})
