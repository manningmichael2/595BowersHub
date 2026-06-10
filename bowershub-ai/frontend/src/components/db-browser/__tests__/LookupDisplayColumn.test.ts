/**
 * Property-based tests for lookup display column selection.
 *
 * **Validates: Requirements 17.2**
 *
 * When rendering FK dropdowns, the system selects a "display column" from the
 * referenced table using this priority:
 *   1. Column named `name` → use it
 *   2. Column named `title` → use it
 *   3. Column named `description` → use it
 *   4. First column with data_type 'text' or 'character varying' → use it
 *   5. Otherwise use the PK column value as label
 *
 * These tests verify the selection algorithm always picks correctly regardless
 * of what columns are present or their ordering.
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'

// --- Types ---

interface ColumnDef {
  column_name: string
  data_type: string
}

// --- Pure selection function (mirrors backend logic) ---

const PREFERRED_NAMES = ['name', 'title', 'description'] as const
const TEXT_TYPES = new Set(['text', 'character varying'])

/**
 * Select the display column from a list of columns in ordinal position order.
 * Returns the column name to use as the display label, or null if the PK
 * column should be used (i.e., no suitable text column found).
 */
function selectDisplayColumn(columns: ColumnDef[]): string | null {
  // Check for preferred column names
  const colNames = new Set(columns.map((c) => c.column_name))
  for (const preferred of PREFERRED_NAMES) {
    if (colNames.has(preferred)) {
      return preferred
    }
  }

  // Fallback: first text/varchar column (in ordinal position order)
  for (const col of columns) {
    if (TEXT_TYPES.has(col.data_type)) {
      return col.column_name
    }
  }

  // No suitable display column found — caller uses PK
  return null
}

// --- Generators ---

/** Generate a column name that is NOT one of the preferred names */
const nonPreferredName = fc.string({ minLength: 1, maxLength: 30 }).filter(
  (s) => !PREFERRED_NAMES.includes(s as any) && s.trim().length > 0
)

/** Generate a non-text data type */
const nonTextDataType = fc.constantFrom(
  'integer', 'bigint', 'smallint', 'numeric', 'real',
  'double precision', 'boolean', 'date', 'timestamp',
  'timestamp with time zone', 'uuid', 'jsonb', 'bytea'
)

/** Generate a text data type */
const textDataType = fc.constantFrom('text', 'character varying')

/** Generate a column definition with a non-preferred name */
const arbitraryColumn = fc.record({
  column_name: nonPreferredName,
  data_type: fc.oneof(textDataType, nonTextDataType),
})

/** Generate a non-text column with a non-preferred name */
const nonTextColumn = fc.record({
  column_name: nonPreferredName,
  data_type: nonTextDataType,
})

/** Generate a text column with a non-preferred name */
const textColumn = fc.record({
  column_name: nonPreferredName,
  data_type: textDataType,
})

// --- Tests ---

describe('Lookup display column selection', () => {
  it('Property 11a: "name" always wins regardless of other columns present', () => {
    fc.assert(
      fc.property(
        fc.array(arbitraryColumn, { minLength: 0, maxLength: 20 }),
        (otherColumns) => {
          // Inject 'name' at a random position among other columns
          const nameCol: ColumnDef = { column_name: 'name', data_type: 'text' }
          // Filter out any accidental 'name' from generated columns
          const cols = otherColumns.filter((c) => c.column_name !== 'name')
          // Put 'name' somewhere in the list
          const insertPos = cols.length > 0 ? Math.floor(Math.random() * (cols.length + 1)) : 0
          cols.splice(insertPos, 0, nameCol)

          expect(selectDisplayColumn(cols)).toBe('name')
        }
      ),
      { numRuns: 200 }
    )
  })

  it('Property 11b: "title" is selected when "name" is absent', () => {
    fc.assert(
      fc.property(
        fc.array(arbitraryColumn, { minLength: 0, maxLength: 20 }),
        (otherColumns) => {
          const titleCol: ColumnDef = { column_name: 'title', data_type: 'text' }
          // Ensure no 'name' or 'title' in generated columns
          const cols = otherColumns.filter(
            (c) => c.column_name !== 'name' && c.column_name !== 'title'
          )
          const insertPos = cols.length > 0 ? Math.floor(Math.random() * (cols.length + 1)) : 0
          cols.splice(insertPos, 0, titleCol)

          expect(selectDisplayColumn(cols)).toBe('title')
        }
      ),
      { numRuns: 200 }
    )
  })

  it('Property 11c: "description" is selected when neither "name" nor "title" exist', () => {
    fc.assert(
      fc.property(
        fc.array(arbitraryColumn, { minLength: 0, maxLength: 20 }),
        (otherColumns) => {
          const descCol: ColumnDef = { column_name: 'description', data_type: 'text' }
          // Ensure no preferred names in generated columns
          const cols = otherColumns.filter(
            (c) => !PREFERRED_NAMES.includes(c.column_name as any)
          )
          const insertPos = cols.length > 0 ? Math.floor(Math.random() * (cols.length + 1)) : 0
          cols.splice(insertPos, 0, descCol)

          expect(selectDisplayColumn(cols)).toBe('description')
        }
      ),
      { numRuns: 200 }
    )
  })

  it('Property 11d: first text column is selected when no preferred names exist', () => {
    fc.assert(
      fc.property(
        fc.array(nonTextColumn, { minLength: 0, maxLength: 10 }),
        textColumn,
        fc.array(arbitraryColumn, { minLength: 0, maxLength: 10 }),
        (leadingNonText, firstText, trailing) => {
          // Build a column list: non-text columns, then a text column, then anything
          // But ensure no preferred names anywhere
          const allCols = [
            ...leadingNonText,
            firstText,
            ...trailing,
          ].filter((c) => !PREFERRED_NAMES.includes(c.column_name as any))

          // If filtering removed the text column, skip this case
          if (!allCols.some((c) => TEXT_TYPES.has(c.data_type))) return

          const result = selectDisplayColumn(allCols)

          // Result should be the first text column in ordinal order
          const expectedFirst = allCols.find((c) => TEXT_TYPES.has(c.data_type))!
          expect(result).toBe(expectedFirst.column_name)
        }
      ),
      { numRuns: 200 }
    )
  })

  it('Property 11e: returns null (PK fallback) when no text columns exist', () => {
    fc.assert(
      fc.property(
        fc.array(nonTextColumn, { minLength: 1, maxLength: 20 }).filter(
          (cols) => cols.every((c) => !PREFERRED_NAMES.includes(c.column_name as any))
        ),
        (columns) => {
          expect(selectDisplayColumn(columns)).toBeNull()
        }
      ),
      { numRuns: 200 }
    )
  })

  it('Property 11f: preferred name priority is strict (name > title > description)', () => {
    fc.assert(
      fc.property(
        fc.subarray(
          [
            { column_name: 'name', data_type: 'text' },
            { column_name: 'title', data_type: 'text' },
            { column_name: 'description', data_type: 'text' },
          ] as ColumnDef[],
          { minLength: 2, maxLength: 3 }
        ),
        fc.array(nonTextColumn, { minLength: 0, maxLength: 5 }),
        (preferredCols, extras) => {
          // Shuffle preferred columns into the extras in any order
          const allCols = [...extras, ...preferredCols]
          // Shuffle
          for (let i = allCols.length - 1; i > 0; i--) {
            const j = Math.floor(Math.random() * (i + 1))
            ;[allCols[i], allCols[j]] = [allCols[j], allCols[i]]
          }

          const result = selectDisplayColumn(allCols)

          // Result should be the highest-priority preferred name present
          const names = new Set(allCols.map((c) => c.column_name))
          if (names.has('name')) expect(result).toBe('name')
          else if (names.has('title')) expect(result).toBe('title')
          else expect(result).toBe('description')
        }
      ),
      { numRuns: 200 }
    )
  })
})
