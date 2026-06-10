/**
 * Property-based tests for duplicate row field preservation.
 *
 * **Validates: Requirements 13.1, 13.3**
 *
 * The duplicate row feature copies all field values from an existing row
 * except the primary key and timestamp columns (created_at, updated_at, archived_at).
 * These tests verify that the duplication logic:
 * 1. Preserves all non-PK, non-timestamp fields exactly
 * 2. Removes the PK field from the duplicated values
 * 3. Removes timestamp fields from the duplicated values
 * 4. Empty rows (no fields) produce empty output
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import type { ColumnMeta } from '../../../stores/db-browser'

// --- Replicate the production duplicate logic from DetailView.tsx ---

/** Timestamp column names that are stripped during duplication */
const TIMESTAMP_COLUMNS = ['created_at', 'updated_at', 'archived_at'] as const

/**
 * Pure implementation of the duplicate row logic from DetailView.tsx.
 * Given columns metadata and a row's values, returns only the fields
 * that should be preserved for the duplicate.
 */
function prepareDuplicateValues(
  columns: ColumnMeta[],
  row: Record<string, any>
): Record<string, any> {
  const valuesToCopy: Record<string, any> = {}
  columns.forEach(col => {
    // Skip PK column
    if (col.is_pk) return
    // Skip timestamp columns
    if ((TIMESTAMP_COLUMNS as readonly string[]).includes(col.column_name)) return
    // Copy the value
    valuesToCopy[col.column_name] = row[col.column_name]
  })
  return valuesToCopy
}

// --- Arbitraries -----------------------------------------------------------

/** Generate a valid non-special column name (not a timestamp and not 'id') */
const arbRegularColumnName = fc.stringMatching(/^[a-z][a-z0-9_]{1,30}$/).filter(
  name => !TIMESTAMP_COLUMNS.includes(name as any) && name !== 'id'
)

/** Generate an arbitrary JSON-safe value for a row field */
const arbFieldValue = fc.oneof(
  fc.string({ maxLength: 100 }),
  fc.integer(),
  fc.double({ noNaN: true, noDefaultInfinity: true }),
  fc.boolean(),
  fc.constant(null),
  fc.date().map(d => d.toISOString())
)

/** Generate a ColumnMeta that is NOT a PK and NOT a timestamp */
const arbRegularColumn = (name: string): fc.Arbitrary<ColumnMeta> =>
  fc.record({
    column_name: fc.constant(name),
    data_type: fc.constantFrom('text', 'integer', 'numeric', 'boolean', 'date', 'timestamp with time zone'),
    is_nullable: fc.constantFrom('YES', 'NO'),
    column_default: fc.constant(null),
    is_pk: fc.constant(false),
  })

/** Generate a PK column */
const arbPkColumn: fc.Arbitrary<ColumnMeta> = fc.record({
  column_name: fc.constant('id'),
  data_type: fc.constantFrom('integer', 'bigint', 'uuid'),
  is_nullable: fc.constant('NO'),
  column_default: fc.constant("nextval('seq')"),
  is_pk: fc.constant(true),
})

/** Generate a timestamp column */
const arbTimestampColumn = (name: typeof TIMESTAMP_COLUMNS[number]): fc.Arbitrary<ColumnMeta> =>
  fc.record({
    column_name: fc.constant(name),
    data_type: fc.constant('timestamp with time zone'),
    is_nullable: fc.constantFrom('YES', 'NO'),
    column_default: fc.constant('now()'),
    is_pk: fc.constant(false),
  })

/**
 * Generate a full table schema: 1 PK + 0-3 timestamp columns + 1-10 regular columns.
 * Also generates a row with values for all columns.
 */
const arbTableWithRow = fc.integer({ min: 1, max: 10 }).chain(numRegular => {
  // Generate unique regular column names
  return fc.uniqueArray(arbRegularColumnName, { minLength: numRegular, maxLength: numRegular })
    .chain(regularNames => {
      // Choose which timestamp columns to include
      return fc.subarray(TIMESTAMP_COLUMNS as unknown as string[], { minLength: 0, maxLength: 3 })
        .chain(timestampNames => {
          // Build column metas
          const pkCol = arbPkColumn
          const regularCols = regularNames.map(name => arbRegularColumn(name))
          const timestampCols = (timestampNames as typeof TIMESTAMP_COLUMNS[number][]).map(name => arbTimestampColumn(name))

          return fc.tuple(
            pkCol,
            fc.tuple(...regularCols),
            fc.tuple(...timestampCols),
            // PK value
            fc.integer({ min: 1, max: 100000 }),
            // Regular field values
            fc.tuple(...regularNames.map(() => arbFieldValue)),
            // Timestamp values
            fc.tuple(...timestampNames.map(() => fc.date().map(d => d.toISOString())))
          ).map(([pk, regulars, timestamps, pkValue, regularValues, timestampValues]) => {
            const columns: ColumnMeta[] = [pk, ...regulars, ...timestamps]
            const row: Record<string, any> = {}

            // Build the row
            row[pk.column_name] = pkValue
            regulars.forEach((col, i) => {
              row[col.column_name] = regularValues[i]
            })
            timestamps.forEach((col, i) => {
              row[col.column_name] = timestampValues[i]
            })

            return {
              columns,
              row,
              regularNames,
              timestampNames,
              pkName: pk.column_name,
            }
          })
        })
    })
})

// --- Tests -----------------------------------------------------------------

describe('Duplicate row field preservation', () => {
  it('Property 9a: All non-PK, non-timestamp fields are preserved exactly', () => {
    fc.assert(
      fc.property(arbTableWithRow, ({ columns, row, regularNames }) => {
        const duplicated = prepareDuplicateValues(columns, row)

        // Every regular column must be present with its exact value
        for (const name of regularNames) {
          expect(duplicated).toHaveProperty(name)
          expect(duplicated[name]).toEqual(row[name])
        }
      }),
      { numRuns: 500 }
    )
  })

  it('Property 9b: PK field is removed from the duplicated values', () => {
    fc.assert(
      fc.property(arbTableWithRow, ({ columns, row, pkName }) => {
        const duplicated = prepareDuplicateValues(columns, row)

        // PK must NOT appear in duplicated values
        expect(duplicated).not.toHaveProperty(pkName)
      }),
      { numRuns: 500 }
    )
  })

  it('Property 9c: Timestamp fields are removed from the duplicated values', () => {
    fc.assert(
      fc.property(arbTableWithRow, ({ columns, row, timestampNames }) => {
        const duplicated = prepareDuplicateValues(columns, row)

        // None of the timestamp columns should be in the result
        for (const name of timestampNames) {
          expect(duplicated).not.toHaveProperty(name)
        }
      }),
      { numRuns: 500 }
    )
  })

  it('Property 9d: Empty rows (no regular fields) produce empty output', () => {
    // A table with only PK + timestamp columns should produce an empty duplicate
    const arbEmptyTable = fc.subarray(TIMESTAMP_COLUMNS as unknown as string[], { minLength: 0, maxLength: 3 })
      .chain(timestampNames => {
        return fc.tuple(
          arbPkColumn,
          fc.tuple(...(timestampNames as typeof TIMESTAMP_COLUMNS[number][]).map(name => arbTimestampColumn(name))),
          fc.integer({ min: 1, max: 100000 }),
          fc.tuple(...timestampNames.map(() => fc.date().map(d => d.toISOString())))
        ).map(([pk, timestamps, pkValue, timestampValues]) => {
          const columns: ColumnMeta[] = [pk, ...timestamps]
          const row: Record<string, any> = {}
          row[pk.column_name] = pkValue
          timestamps.forEach((col, i) => {
            row[col.column_name] = timestampValues[i]
          })
          return { columns, row }
        })
      })

    fc.assert(
      fc.property(arbEmptyTable, ({ columns, row }) => {
        const duplicated = prepareDuplicateValues(columns, row)
        expect(Object.keys(duplicated)).toHaveLength(0)
      }),
      { numRuns: 200 }
    )
  })

  it('Property 9e: Output key count equals number of non-PK non-timestamp columns', () => {
    fc.assert(
      fc.property(arbTableWithRow, ({ columns, regularNames }) => {
        const row: Record<string, any> = {}
        columns.forEach(col => { row[col.column_name] = 'test' })

        const duplicated = prepareDuplicateValues(columns, row)
        expect(Object.keys(duplicated)).toHaveLength(regularNames.length)
      }),
      { numRuns: 500 }
    )
  })
})
