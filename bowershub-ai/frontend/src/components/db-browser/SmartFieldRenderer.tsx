/**
 * SmartFieldRenderer — central field rendering component for the DB Browser.
 *
 * Determines which input widget to render for a given column using this priority chain:
 * 1. Field Hint exists → use the `input_type` from `fieldHints[column_name]`
 * 2. FK constraint detected → render as LookupField (FK dropdown with type-ahead)
 * 3. Postgres type fallback → map data_type to default widget
 *
 * Supports compact mode (inline cell editing, no label, fixed 36px height)
 * and normal mode (full detail view form, label above input).
 *
 * _Requirements: 8.1, 24.1, 24.3_
 */

import { useDbBrowserStore, type ColumnMeta, type FieldHint } from '../../stores/db-browser'
import FractionField from './fields/FractionField'
import { TextField, NumberField, BooleanField, DateField, UrlField, TextareaField, SelectField } from './fields'
import LookupField from './fields/LookupField'

// ---- Props ----------------------------------------------------------------

export interface SmartFieldRendererProps {
  column: ColumnMeta
  value: any
  onChange: (value: any) => void
  compact?: boolean
  readOnly?: boolean
  /** Hide the label (when parent component renders its own label) */
  hideLabel?: boolean
  /** Current table's schema — needed for FK lookup API calls */
  schema?: string
  /** Current table name — needed for FK lookup API calls */
  table?: string
}

// ---- Component ------------------------------------------------------------

export default function SmartFieldRenderer({
  column,
  value,
  onChange,
  compact = false,
  readOnly = false,
  hideLabel = false,
  schema,
  table,
}: SmartFieldRendererProps) {
  const fieldHints = useDbBrowserStore(s => s.fieldHints)
  const activeSchema = useDbBrowserStore(s => s.activeSchema)
  const activeTable = useDbBrowserStore(s => s.activeTable)
  const hint = fieldHints[column.column_name] ?? null

  // Resolve schema/table: prefer explicit props, fall back to store
  const resolvedSchema = schema ?? activeSchema ?? ''
  const resolvedTable = table ?? activeTable ?? ''

  // Resolve what to render
  const resolved = resolveFieldType(column, hint)

  // Container styling based on compact vs normal mode
  const containerClass = compact
    ? 'flex items-center w-full'
    : 'flex flex-col gap-1 w-full'

  return (
    <div className={containerClass}>
      {/* Label: only in normal mode and when not hidden */}
      {!compact && !hideLabel && (
        <label
          className="text-xs font-medium"
          style={{ color: 'var(--color-text-muted)' }}
        >
          {column.column_name}
          {column.is_nullable === 'NO' && (
            <span style={{ color: 'var(--color-primary)' }}> *</span>
          )}
        </label>
      )}

      {/* Input widget */}
      {renderWidget(resolved, value, onChange, compact, readOnly, column, hint, resolvedSchema, resolvedTable)}
    </div>
  )
}

// ---- Resolution Logic -----------------------------------------------------

type ResolvedFieldType =
  | 'text'
  | 'number'
  | 'fraction'
  | 'boolean'
  | 'date'
  | 'datetime'
  | 'textarea'
  | 'select'
  | 'url'
  | 'lookup'
  | 'uuid'

interface ResolvedField {
  type: ResolvedFieldType
  source: 'hint' | 'fk' | 'type_fallback'
}

/**
 * Resolves the field type using the priority chain:
 * 1. Field Hint → use input_type
 * 2. FK constraint → lookup
 * 3. Postgres type fallback
 */
export function resolveFieldType(column: ColumnMeta, hint: FieldHint | null): ResolvedField {
  // Priority 1: Field Hint
  if (hint) {
    const mapped = mapHintToResolved(hint.input_type)
    return { type: mapped, source: 'hint' }
  }

  // Priority 2: FK constraint
  if (column.fk_table) {
    return { type: 'lookup', source: 'fk' }
  }

  // Priority 3: Postgres type fallback
  const type = mapPostgresType(column.data_type)
  return { type, source: 'type_fallback' }
}

function mapHintToResolved(inputType: FieldHint['input_type']): ResolvedFieldType {
  switch (inputType) {
    case 'text': return 'text'
    case 'number': return 'number'
    case 'fraction': return 'fraction'
    case 'select': return 'select'
    case 'url': return 'url'
    case 'date': return 'date'
    case 'boolean': return 'boolean'
    case 'textarea': return 'textarea'
    default: return 'text'
  }
}

/**
 * Maps a Postgres data_type to a resolved field type per the design spec.
 */
export function mapPostgresType(dataType: string): ResolvedFieldType {
  const dt = dataType.toLowerCase()

  // Text types
  if (dt === 'text' || dt === 'character varying' || dt === 'varchar' || dt === 'char' || dt === 'character') {
    return 'text'
  }

  // Integer types
  if (dt === 'integer' || dt === 'bigint' || dt === 'smallint' || dt === 'serial' || dt === 'bigserial' || dt === 'smallserial') {
    return 'number'
  }

  // Decimal/floating types
  if (dt === 'numeric' || dt === 'real' || dt === 'double precision' || dt === 'decimal' || dt === 'float' || dt === 'float4' || dt === 'float8') {
    return 'number'
  }

  // Boolean
  if (dt === 'boolean' || dt === 'bool') {
    return 'boolean'
  }

  // Date (no time)
  if (dt === 'date') {
    return 'date'
  }

  // Timestamp types → datetime mode
  if (dt.startsWith('timestamp')) {
    return 'datetime'
  }

  // UUID → read-only text
  if (dt === 'uuid') {
    return 'uuid'
  }

  // JSON types → textarea
  if (dt === 'json' || dt === 'jsonb') {
    return 'textarea'
  }

  // Everything else → text
  return 'text'
}

// ---- Widget Rendering -----------------------------------------------------

function renderWidget(
  resolved: ResolvedField,
  value: any,
  onChange: (value: any) => void,
  compact: boolean,
  readOnly: boolean,
  column: ColumnMeta,
  hint: FieldHint | null,
  schema: string,
  table: string,
) {
  const isDisabled = readOnly || resolved.type === 'uuid'
  const commonProps = {
    value,
    onChange,
    compact,
    readOnly: isDisabled,
    prefix: hint?.prefix ?? null,
    suffix: hint?.suffix ?? null,
    placeholder: hint?.placeholder ?? null,
  }

  switch (resolved.type) {
    case 'text':
      return <TextField {...commonProps} />

    case 'url':
      return <UrlField {...commonProps} />

    case 'uuid':
      return <TextField {...commonProps} readOnly />

    case 'number':
      return (
        <NumberField
          {...commonProps}
          min={hint?.min_val ?? null}
          max={hint?.max_val ?? null}
          step={hint?.step ?? (isIntegerType(column.data_type) ? 1 : null)}
        />
      )

    case 'fraction':
      return (
        <FractionField
          value={value}
          onChange={onChange}
          compact={compact}
          readOnly={isDisabled}
          suffix={hint?.suffix ?? null}
        />
      )

    case 'boolean':
      return <BooleanField {...commonProps} />

    case 'date':
      return <DateField {...commonProps} />

    case 'datetime':
      return <DateField {...commonProps} includeTime />

    case 'textarea':
      return <TextareaField {...commonProps} />

    case 'select':
      return <SelectField {...commonProps} options={hint?.options ?? null} />

    case 'lookup':
      return (
        <LookupField
          value={value}
          onChange={onChange}
          compact={compact}
          readOnly={isDisabled}
          column={column}
          schema={schema}
          table={table}
        />
      )

    default:
      return <TextField {...commonProps} />
  }
}

// ---- Helpers --------------------------------------------------------------

function isIntegerType(dataType: string): boolean {
  const dt = dataType.toLowerCase()
  return (
    dt === 'integer' ||
    dt === 'bigint' ||
    dt === 'smallint' ||
    dt === 'serial' ||
    dt === 'bigserial' ||
    dt === 'smallserial'
  )
}
