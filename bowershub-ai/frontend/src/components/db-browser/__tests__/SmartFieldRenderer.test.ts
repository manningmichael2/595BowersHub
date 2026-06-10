/**
 * Property-based tests for SmartFieldRenderer resolution logic.
 *
 * **Validates: Requirements 8.1, 24.1, 24.3**
 *
 * Tests two core properties:
 * - Property 6: Smart field hint resolution — field hints always override type defaults
 * - Property 8: Type-based fallback rendering — Postgres types map correctly when no hints exist
 */

import { describe, it, expect } from 'vitest'
import * as fc from 'fast-check'
import { resolveFieldType, mapPostgresType } from '../SmartFieldRenderer'
import type { ColumnMeta, FieldHint } from '../../../stores/db-browser'

// ---- Arbitraries ----------------------------------------------------------

/** Valid FieldHint input_type values */
const fieldHintInputTypes = [
  'text', 'number', 'fraction', 'select', 'url', 'date', 'boolean', 'textarea',
] as const

/** Arbitrary for a FieldHint input_type */
const arbInputType = fc.constantFrom(...fieldHintInputTypes)

/** Arbitrary for a FieldHint object */
const arbFieldHint: fc.Arbitrary<FieldHint> = fc.record({
  column_name: fc.string({ minLength: 1, maxLength: 50 }),
  input_type: arbInputType,
  options: fc.oneof(fc.constant(null), fc.array(fc.string(), { minLength: 1, maxLength: 5 })),
  prefix: fc.oneof(fc.constant(null), fc.string({ maxLength: 10 })),
  suffix: fc.oneof(fc.constant(null), fc.string({ maxLength: 10 })),
  min_val: fc.oneof(fc.constant(null), fc.integer({ min: -1000, max: 1000 })),
  max_val: fc.oneof(fc.constant(null), fc.integer({ min: -1000, max: 1000 })),
  step: fc.oneof(fc.constant(null), fc.double({ min: 0.01, max: 100, noNaN: true })),
  placeholder: fc.oneof(fc.constant(null), fc.string({ maxLength: 50 })),
})

/** Arbitrary Postgres data types — a mix of known and unknown types */
const knownPostgresTypes = [
  'text', 'character varying', 'varchar', 'char', 'character',
  'integer', 'bigint', 'smallint', 'serial', 'bigserial', 'smallserial',
  'numeric', 'real', 'double precision', 'decimal', 'float', 'float4', 'float8',
  'boolean', 'bool',
  'date',
  'timestamp', 'timestamp without time zone', 'timestamp with time zone', 'timestamptz',
  'uuid',
  'json', 'jsonb',
]

const unknownPostgresTypes = [
  'bytea', 'inet', 'cidr', 'macaddr', 'tsvector', 'tsquery',
  'point', 'line', 'box', 'circle', 'polygon', 'path',
  'interval', 'money', 'bit', 'bit varying', 'xml',
]

const arbDataType = fc.oneof(
  fc.constantFrom(...knownPostgresTypes),
  fc.constantFrom(...unknownPostgresTypes),
)

/** Arbitrary for a ColumnMeta object (without FK) */
const arbColumnMetaNoFK: fc.Arbitrary<ColumnMeta> = fc.record({
  column_name: fc.string({ minLength: 1, maxLength: 50 }),
  data_type: arbDataType,
  is_nullable: fc.constantFrom('YES', 'NO'),
  column_default: fc.oneof(fc.constant(null), fc.string({ maxLength: 20 })),
  is_pk: fc.boolean(),
})

/** Arbitrary for a ColumnMeta object with a FK */
const arbColumnMetaWithFK: fc.Arbitrary<ColumnMeta> = fc.record({
  column_name: fc.string({ minLength: 1, maxLength: 50 }),
  data_type: arbDataType,
  is_nullable: fc.constantFrom('YES', 'NO'),
  column_default: fc.oneof(fc.constant(null), fc.string({ maxLength: 20 })),
  is_pk: fc.boolean(),
  fk_schema: fc.string({ minLength: 1, maxLength: 20 }),
  fk_table: fc.string({ minLength: 1, maxLength: 50 }),
  fk_column: fc.string({ minLength: 1, maxLength: 50 }),
})

/** Arbitrary for a ColumnMeta (can be with or without FK) */
const arbColumnMeta: fc.Arbitrary<ColumnMeta> = fc.oneof(
  arbColumnMetaNoFK,
  arbColumnMetaWithFK,
)

// ---- Property 6: Smart field hint resolution ------------------------------

describe('Property 6: Smart field hint resolution', () => {
  it('when a FieldHint exists, resolved type matches the hint input_type and source is "hint"', () => {
    fc.assert(
      fc.property(arbColumnMeta, arbFieldHint, (column, hint) => {
        const resolved = resolveFieldType(column, hint)

        // Source should always be 'hint' when a hint is provided
        expect(resolved.source).toBe('hint')

        // The mapped hint type should correspond to the hint's input_type
        // mapHintToResolved maps each input_type to its resolved equivalent
        const expectedTypeMap: Record<FieldHint['input_type'], string> = {
          text: 'text',
          number: 'number',
          fraction: 'fraction',
          select: 'select',
          url: 'url',
          date: 'date',
          boolean: 'boolean',
          textarea: 'textarea',
        }
        expect(resolved.type).toBe(expectedTypeMap[hint.input_type])
      }),
      { numRuns: 300 }
    )
  })

  it('hint always takes priority regardless of column data_type', () => {
    fc.assert(
      fc.property(arbDataType, arbInputType, (dataType, inputType) => {
        const column: ColumnMeta = {
          column_name: 'test_col',
          data_type: dataType,
          is_nullable: 'YES',
          column_default: null,
          is_pk: false,
        }
        const hint: FieldHint = {
          column_name: 'test_col',
          input_type: inputType,
          options: null,
          prefix: null,
          suffix: null,
          min_val: null,
          max_val: null,
          step: null,
          placeholder: null,
        }

        const resolved = resolveFieldType(column, hint)
        expect(resolved.source).toBe('hint')
        expect(resolved.type).toBe(inputType)
      }),
      { numRuns: 300 }
    )
  })

  it('hint takes priority even when FK is present on column', () => {
    fc.assert(
      fc.property(arbColumnMetaWithFK, arbFieldHint, (column, hint) => {
        const resolved = resolveFieldType(column, hint)

        // Even with FK on column, hint should win
        expect(resolved.source).toBe('hint')
        // Result type comes from hint, not 'lookup'
        expect(resolved.type).not.toBe('lookup')
      }),
      { numRuns: 200 }
    )
  })
})

// ---- Property 8: Type-based fallback rendering ----------------------------

describe('Property 8: Type-based fallback rendering', () => {
  it('when no hint and no FK, resolved type maps from Postgres data_type', () => {
    fc.assert(
      fc.property(arbColumnMetaNoFK, (column) => {
        const resolved = resolveFieldType(column, null)

        expect(resolved.source).toBe('type_fallback')
        // The type should match what mapPostgresType returns for this data_type
        expect(resolved.type).toBe(mapPostgresType(column.data_type))
      }),
      { numRuns: 300 }
    )
  })

  it('when no hint but FK exists, resolved type is "lookup"', () => {
    fc.assert(
      fc.property(arbColumnMetaWithFK, (column) => {
        const resolved = resolveFieldType(column, null)

        expect(resolved.source).toBe('fk')
        expect(resolved.type).toBe('lookup')
      }),
      { numRuns: 200 }
    )
  })

  it('text types map to "text"', () => {
    const textTypes = ['text', 'character varying', 'varchar', 'char', 'character']
    fc.assert(
      fc.property(fc.constantFrom(...textTypes), (dataType) => {
        expect(mapPostgresType(dataType)).toBe('text')
      }),
      { numRuns: 50 }
    )
  })

  it('integer types map to "number"', () => {
    const intTypes = ['integer', 'bigint', 'smallint', 'serial', 'bigserial', 'smallserial']
    fc.assert(
      fc.property(fc.constantFrom(...intTypes), (dataType) => {
        expect(mapPostgresType(dataType)).toBe('number')
      }),
      { numRuns: 50 }
    )
  })

  it('decimal/floating types map to "number"', () => {
    const decTypes = ['numeric', 'real', 'double precision', 'decimal', 'float', 'float4', 'float8']
    fc.assert(
      fc.property(fc.constantFrom(...decTypes), (dataType) => {
        expect(mapPostgresType(dataType)).toBe('number')
      }),
      { numRuns: 50 }
    )
  })

  it('boolean types map to "boolean"', () => {
    const boolTypes = ['boolean', 'bool']
    fc.assert(
      fc.property(fc.constantFrom(...boolTypes), (dataType) => {
        expect(mapPostgresType(dataType)).toBe('boolean')
      }),
      { numRuns: 20 }
    )
  })

  it('date maps to "date"', () => {
    expect(mapPostgresType('date')).toBe('date')
  })

  it('timestamp types map to "datetime"', () => {
    const tsTypes = ['timestamp', 'timestamp without time zone', 'timestamp with time zone', 'timestamptz']
    fc.assert(
      fc.property(fc.constantFrom(...tsTypes), (dataType) => {
        expect(mapPostgresType(dataType)).toBe('datetime')
      }),
      { numRuns: 30 }
    )
  })

  it('uuid maps to "uuid"', () => {
    expect(mapPostgresType('uuid')).toBe('uuid')
  })

  it('json/jsonb maps to "textarea"', () => {
    const jsonTypes = ['json', 'jsonb']
    fc.assert(
      fc.property(fc.constantFrom(...jsonTypes), (dataType) => {
        expect(mapPostgresType(dataType)).toBe('textarea')
      }),
      { numRuns: 20 }
    )
  })

  it('unknown types fall back to "text"', () => {
    fc.assert(
      fc.property(fc.constantFrom(...unknownPostgresTypes), (dataType) => {
        expect(mapPostgresType(dataType)).toBe('text')
      }),
      { numRuns: 50 }
    )
  })

  it('mapPostgresType always returns a valid ResolvedFieldType', () => {
    const validTypes = ['text', 'number', 'fraction', 'boolean', 'date', 'datetime', 'textarea', 'select', 'url', 'lookup', 'uuid']
    fc.assert(
      fc.property(fc.string(), (dataType) => {
        const result = mapPostgresType(dataType)
        expect(validTypes).toContain(result)
      }),
      { numRuns: 200 }
    )
  })
})
