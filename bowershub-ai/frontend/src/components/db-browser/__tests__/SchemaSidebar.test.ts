/**
 * Property-based tests for SchemaSidebar alphabetical ordering.
 *
 * **Validates: Requirements 2.2**
 *
 * The SchemaSidebar sorts tables alphabetically within each schema using
 * case-insensitive locale comparison. These tests verify the sort function
 * produces correct lexicographic order for any set of table names.
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

/**
 * Pure sort function matching SchemaSidebar's table ordering logic.
 * Extracted here so we can test it without DOM dependencies.
 */
function sortTableNames(names: string[]): string[] {
  return [...names].sort((a, b) =>
    a.localeCompare(b, undefined, { sensitivity: 'base' })
  )
}

describe('SchemaSidebar alphabetical ordering', () => {
  it('Property 1: sorted output is in lexicographic order (case-insensitive)', () => {
    fc.assert(
      fc.property(fc.array(fc.string()), (names) => {
        const sorted = sortTableNames(names)
        for (let i = 0; i < sorted.length - 1; i++) {
          expect(
            sorted[i].localeCompare(sorted[i + 1], undefined, { sensitivity: 'base' })
          ).toBeLessThanOrEqual(0)
        }
      }),
      { numRuns: 200 }
    )
  })

  it('Property 2: sorting is idempotent (sorting twice equals sorting once)', () => {
    fc.assert(
      fc.property(fc.array(fc.string()), (names) => {
        const sortedOnce = sortTableNames(names)
        const sortedTwice = sortTableNames(sortedOnce)
        expect(sortedTwice).toEqual(sortedOnce)
      }),
      { numRuns: 200 }
    )
  })

  it('Property 3: sort preserves all elements (same length and same multiset)', () => {
    fc.assert(
      fc.property(fc.array(fc.string()), (names) => {
        const sorted = sortTableNames(names)
        expect(sorted).toHaveLength(names.length)
        // Every element in original appears in sorted (and vice versa)
        const originalCounts = new Map<string, number>()
        const sortedCounts = new Map<string, number>()
        for (const n of names) originalCounts.set(n, (originalCounts.get(n) ?? 0) + 1)
        for (const n of sorted) sortedCounts.set(n, (sortedCounts.get(n) ?? 0) + 1)
        expect(sortedCounts).toEqual(originalCounts)
      }),
      { numRuns: 200 }
    )
  })

  it('Property 4: single-element and empty arrays are already sorted', () => {
    fc.assert(
      fc.property(
        fc.oneof(fc.constant([]), fc.string().map((s) => [s])),
        (names) => {
          const sorted = sortTableNames(names)
          expect(sorted).toEqual(names)
        }
      ),
      { numRuns: 100 }
    )
  })
})
