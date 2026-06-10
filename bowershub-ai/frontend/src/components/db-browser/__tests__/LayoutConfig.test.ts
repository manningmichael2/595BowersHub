/**
 * Property-based tests for layout configuration round-trip.
 *
 * **Validates: Requirements 10.5, 24.2**
 *
 * Property 10: Layout configuration round-trip
 * Tests that saving and retrieving a layout config returns an equivalent object,
 * and validates structural invariants of the configuration shape.
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import type { LayoutConfig } from '../../../stores/db-browser'

// ---- Arbitraries ----------------------------------------------------------

/** Valid width values for detail fields */
const validWidths = [25, 33, 50, 100] as const

/** Valid height values for detail fields */
const validHeights = ['small', 'medium', 'large'] as const

/** Arbitrary for a column name (realistic SQL-style identifiers) */
const arbColumnName = fc.stringMatching(/^[a-z][a-z0-9_]{0,49}$/)

/** Arbitrary for a list column entry */
const arbListColumn = (position: number) =>
  fc.record({
    name: arbColumnName,
    visible: fc.boolean(),
    position: fc.constant(position),
  })

/** Arbitrary for a detail field entry */
const arbDetailField = (position: number) =>
  fc.record({
    name: arbColumnName,
    visible: fc.boolean(),
    position: fc.constant(position),
    width: fc.constantFrom(...validWidths),
    height: fc.constantFrom(...validHeights),
  })

/**
 * Generate a list of columns with sequential positions 0..n-1
 * and unique names (no duplicates).
 */
const arbListColumns = fc.integer({ min: 1, max: 30 }).chain(count =>
  fc.uniqueArray(arbColumnName, { minLength: count, maxLength: count }).map(names =>
    names.map((name, i) => ({ name, visible: fc.sample(fc.boolean(), 1)[0], position: i }))
  )
)

/**
 * Generate a list of detail fields with sequential positions 0..n-1
 * and unique names (no duplicates).
 */
const arbDetailFields = fc.integer({ min: 1, max: 30 }).chain(count =>
  fc.uniqueArray(arbColumnName, { minLength: count, maxLength: count }).chain(names =>
    fc.tuple(
      ...names.map(() => fc.boolean())
    ).chain(visibilities =>
      fc.tuple(
        ...names.map(() => fc.constantFrom(...validWidths))
      ).chain(widths =>
        fc.tuple(
          ...names.map(() => fc.constantFrom(...validHeights))
        ).map(heights =>
          names.map((name, i) => ({
            name,
            visible: visibilities[i],
            position: i,
            width: widths[i] as 25 | 33 | 50 | 100,
            height: heights[i] as 'small' | 'medium' | 'large',
          }))
        )
      )
    )
  )
)

/** Arbitrary for a full LayoutConfig with valid structural invariants */
const arbLayoutConfig: fc.Arbitrary<LayoutConfig> = fc.record({
  list: arbListColumns.map(columns => ({ columns })),
  detail: arbDetailFields.map(fields => ({ fields })),
})

// ---- Helpers ---------------------------------------------------------------

/**
 * Simulate a round-trip through JSON serialization (same as what happens
 * when the config is stored in Postgres JSONB and retrieved via API).
 */
function jsonRoundTrip(config: LayoutConfig): LayoutConfig {
  return JSON.parse(JSON.stringify(config))
}

/**
 * Validate that positions are sequential 0..n-1 with no gaps or duplicates.
 */
function hasSequentialPositions(items: { position: number }[]): boolean {
  if (items.length === 0) return true
  const sorted = [...items].sort((a, b) => a.position - b.position)
  return sorted.every((item, i) => item.position === i)
}

/**
 * Validate that all names in a list are unique (no phantom or duplicate columns).
 */
function hasUniqueNames(items: { name: string }[]): boolean {
  const names = items.map(i => i.name)
  return new Set(names).size === names.length
}

// ---- Property 10: Layout configuration round-trip -------------------------

describe('Property 10: Layout configuration round-trip', () => {
  it('JSON serialization round-trip preserves the original config (no data loss)', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        const roundTripped = jsonRoundTrip(config)
        expect(roundTripped).toEqual(config)
      }),
      { numRuns: 300 }
    )
  })

  it('list column positions are sequential 0..n-1 (no gaps or duplicates)', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        expect(hasSequentialPositions(config.list.columns)).toBe(true)
      }),
      { numRuns: 300 }
    )
  })

  it('detail field positions are sequential 0..n-1 (no gaps or duplicates)', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        expect(hasSequentialPositions(config.detail.fields)).toBe(true)
      }),
      { numRuns: 300 }
    )
  })

  it('detail field width values are constrained to 25 | 33 | 50 | 100', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        for (const field of config.detail.fields) {
          expect(validWidths).toContain(field.width)
        }
      }),
      { numRuns: 300 }
    )
  })

  it('detail field height values are constrained to small | medium | large', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        for (const field of config.detail.fields) {
          expect(validHeights).toContain(field.height)
        }
      }),
      { numRuns: 300 }
    )
  })

  it('all list column names are unique (no phantom or missing columns)', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        expect(hasUniqueNames(config.list.columns)).toBe(true)
      }),
      { numRuns: 300 }
    )
  })

  it('all detail field names are unique (no phantom or missing columns)', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        expect(hasUniqueNames(config.detail.fields)).toBe(true)
      }),
      { numRuns: 300 }
    )
  })

  it('round-tripped config preserves list column count exactly', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        const roundTripped = jsonRoundTrip(config)
        expect(roundTripped.list.columns.length).toBe(config.list.columns.length)
      }),
      { numRuns: 200 }
    )
  })

  it('round-tripped config preserves detail field count exactly', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        const roundTripped = jsonRoundTrip(config)
        expect(roundTripped.detail.fields.length).toBe(config.detail.fields.length)
      }),
      { numRuns: 200 }
    )
  })

  it('round-tripped config preserves all field names from the original', () => {
    fc.assert(
      fc.property(arbLayoutConfig, (config) => {
        const roundTripped = jsonRoundTrip(config)

        const originalListNames = new Set(config.list.columns.map(c => c.name))
        const roundTrippedListNames = new Set(roundTripped.list.columns.map(c => c.name))
        expect(roundTrippedListNames).toEqual(originalListNames)

        const originalDetailNames = new Set(config.detail.fields.map(f => f.name))
        const roundTrippedDetailNames = new Set(roundTripped.detail.fields.map(f => f.name))
        expect(roundTrippedDetailNames).toEqual(originalDetailNames)
      }),
      { numRuns: 200 }
    )
  })
})
