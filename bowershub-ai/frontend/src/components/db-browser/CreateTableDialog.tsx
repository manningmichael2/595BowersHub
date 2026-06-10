/**
 * CreateTableDialog — modal dialog for creating a new table.
 *
 * Provides:
 * - Schema selector (from store schemas list)
 * - Table name text input
 * - Dynamic column builder: add/remove rows with name, type, nullable, default
 * - "Include image support" checkbox for auto-creating link table
 * - Live SQL preview panel
 * - Create button (calls POST /api/db/tables)
 * - Error handling for conflicts/invalid names
 *
 * _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5_
 */

import { useState, useMemo, useEffect, useCallback } from 'react'
import { useDbBrowserStore } from '../../stores/db-browser'
import { useIsAdmin } from '../../hooks/useIsAdmin'
import { api } from '../../services/api'

// ---- Types ----------------------------------------------------------------

interface ColumnDef {
  id: string
  name: string
  type: ColumnType
  nullable: boolean
  defaultValue: string
}

type ColumnType =
  | 'text'
  | 'integer'
  | 'decimal'
  | 'boolean'
  | 'date'
  | 'timestamp'
  | 'lookup'

// ---- Props ----------------------------------------------------------------

interface CreateTableDialogProps {
  open: boolean
  onClose: () => void
}

// ---- Constants ------------------------------------------------------------

const COLUMN_TYPES: { value: ColumnType; label: string }[] = [
  { value: 'text', label: 'Text' },
  { value: 'integer', label: 'Integer' },
  { value: 'decimal', label: 'Decimal' },
  { value: 'boolean', label: 'Boolean' },
  { value: 'date', label: 'Date' },
  { value: 'timestamp', label: 'Timestamp' },
  { value: 'lookup', label: 'Lookup (FK)' },
]

const PG_TYPE_MAP: Record<ColumnType, string> = {
  text: 'TEXT',
  integer: 'INTEGER',
  decimal: 'NUMERIC',
  boolean: 'BOOLEAN',
  date: 'DATE',
  timestamp: 'TIMESTAMPTZ',
  lookup: 'INTEGER',
}

let columnIdCounter = 0
function nextColumnId(): string {
  return `col_${++columnIdCounter}`
}

function makeEmptyColumn(): ColumnDef {
  return {
    id: nextColumnId(),
    name: '',
    type: 'text',
    nullable: true,
    defaultValue: '',
  }
}

// ---- Helpers: SQL preview -------------------------------------------------

function sanitizeIdentifier(name: string): string {
  // Basic SQL identifier sanitization — lowercase, replace non-alnum with _
  return name
    .toLowerCase()
    .replace(/[^a-z0-9_]/g, '_')
    .replace(/^_+|_+$/g, '')
    .replace(/_+/g, '_')
}

function buildSqlPreview(
  schema: string,
  tableName: string,
  columns: ColumnDef[],
  includeImages: boolean
): string {
  const safeName = sanitizeIdentifier(tableName)
  const safeSchema = sanitizeIdentifier(schema)

  if (!safeName || !safeSchema) {
    return '-- Enter a schema and table name to preview SQL'
  }

  const validColumns = columns.filter(c => c.name.trim() !== '')

  const lines: string[] = []
  lines.push(`CREATE TABLE ${safeSchema}.${safeName} (`)

  // Primary key
  const colLines: string[] = []
  colLines.push(`    id SERIAL PRIMARY KEY`)

  // User-defined columns
  for (const col of validColumns) {
    const colName = sanitizeIdentifier(col.name)
    if (!colName) continue

    let colType = PG_TYPE_MAP[col.type]
    let line = `    ${colName} ${colType}`

    if (!col.nullable) {
      line += ' NOT NULL'
    }
    if (col.defaultValue.trim()) {
      line += ` DEFAULT ${formatDefault(col.defaultValue, col.type)}`
    }
    colLines.push(line)
  }

  // Timestamps
  colLines.push(`    created_at TIMESTAMPTZ NOT NULL DEFAULT now()`)
  colLines.push(`    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()`)

  lines.push(colLines.join(',\n'))
  lines.push(');')

  // Link table for image support
  if (includeImages) {
    lines.push('')
    lines.push(`CREATE TABLE ${safeSchema}.${safeName}_files (`)
    lines.push(`    ${safeName}_id INTEGER NOT NULL REFERENCES ${safeSchema}.${safeName}(id) ON DELETE CASCADE,`)
    lines.push(`    asset_id UUID NOT NULL REFERENCES files.assets(id) ON DELETE CASCADE,`)
    lines.push(`    is_primary BOOLEAN DEFAULT false,`)
    lines.push(`    sort_order INTEGER DEFAULT 0,`)
    lines.push(`    PRIMARY KEY (${safeName}_id, asset_id)`)
    lines.push(');')
  }

  return lines.join('\n')
}

function formatDefault(value: string, type: ColumnType): string {
  const trimmed = value.trim()
  switch (type) {
    case 'text':
      // Wrap in single quotes if not already
      if (trimmed.startsWith("'") && trimmed.endsWith("'")) return trimmed
      return `'${trimmed.replace(/'/g, "''")}'`
    case 'boolean':
      return trimmed.toLowerCase() === 'true' ? 'true' : 'false'
    case 'integer':
    case 'decimal':
      return trimmed
    case 'date':
    case 'timestamp':
      if (trimmed.toLowerCase() === 'now()') return 'now()'
      return `'${trimmed}'`
    case 'lookup':
      return trimmed
    default:
      return `'${trimmed}'`
  }
}

// ---- Component ------------------------------------------------------------

export default function CreateTableDialog({ open, onClose }: CreateTableDialogProps) {
  const isAdmin = useIsAdmin()
  const schemas = useDbBrowserStore(s => s.schemas)
  const loadSchemas = useDbBrowserStore(s => s.loadSchemas)

  // Form state
  const [selectedSchema, setSelectedSchema] = useState<string>('')
  const [tableName, setTableName] = useState('')
  const [columns, setColumns] = useState<ColumnDef[]>([makeEmptyColumn()])
  const [includeImages, setIncludeImages] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Set default schema when schemas load
  useEffect(() => {
    if (open && schemas.length > 0 && !selectedSchema) {
      // Default to first non-public schema, or 'inventory' if available
      const inv = schemas.find(s => s.name === 'inventory')
      const first = schemas[0]
      setSelectedSchema(inv?.name || first?.name || '')
    }
  }, [open, schemas, selectedSchema])

  // Reset form when dialog opens
  useEffect(() => {
    if (open) {
      setTableName('')
      setColumns([makeEmptyColumn()])
      setIncludeImages(false)
      setError(null)
      setSubmitting(false)
      // Don't reset selectedSchema so it persists between opens
    }
  }, [open])

  // Build live SQL preview
  const sqlPreview = useMemo(
    () => buildSqlPreview(selectedSchema, tableName, columns, includeImages),
    [selectedSchema, tableName, columns, includeImages]
  )

  // ---- Column builder actions ----

  const addColumn = useCallback(() => {
    setColumns(prev => [...prev, makeEmptyColumn()])
  }, [])

  const removeColumn = useCallback((id: string) => {
    setColumns(prev => {
      if (prev.length <= 1) return prev
      return prev.filter(c => c.id !== id)
    })
  }, [])

  const updateColumn = useCallback((id: string, field: keyof ColumnDef, value: any) => {
    setColumns(prev =>
      prev.map(c => (c.id === id ? { ...c, [field]: value } : c))
    )
  }, [])

  // ---- Submit ----

  const handleCreate = useCallback(async () => {
    setError(null)

    // Validation
    if (!selectedSchema) {
      setError('Please select a schema.')
      return
    }
    if (!tableName.trim()) {
      setError('Please enter a table name.')
      return
    }
    if (/[^a-zA-Z0-9_]/.test(tableName.trim())) {
      setError('Table name can only contain letters, numbers, and underscores.')
      return
    }

    const validColumns = columns.filter(c => c.name.trim() !== '')
    if (validColumns.length === 0) {
      setError('Please add at least one column.')
      return
    }

    // Check for duplicate column names
    const colNames = validColumns.map(c => sanitizeIdentifier(c.name))
    const dupes = colNames.filter((n, i) => colNames.indexOf(n) !== i)
    if (dupes.length > 0) {
      setError(`Duplicate column name: ${dupes[0]}`)
      return
    }

    setSubmitting(true)

    try {
      await api.post('/api/db/tables', {
        schema: selectedSchema,
        table_name: tableName.trim(),
        columns: validColumns.map(c => ({
          name: sanitizeIdentifier(c.name),
          type: c.type,
          nullable: c.nullable,
          default_value: c.defaultValue.trim() || null,
        })),
        include_link_table: includeImages,
      })

      // Refresh schemas list so the new table shows up
      await loadSchemas()
      onClose()
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Failed to create table'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }, [selectedSchema, tableName, columns, includeImages, loadSchemas, onClose])

  // Close on Escape key
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  if (!open || !isAdmin) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-3xl max-h-[90vh] flex flex-col rounded-lg shadow-xl mx-4"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
        }}
      >
        {/* Header */}
        <div
          className="shrink-0 flex items-center justify-between px-4 py-3 border-b"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <h3
            className="text-sm font-semibold"
            style={{ color: 'var(--color-text)' }}
          >
            Create New Table
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-sm px-2 py-1 rounded transition-opacity hover:opacity-70"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Close dialog"
          >
            ✕
          </button>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 space-y-4">
          {/* Schema + Table name row */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {/* Schema selector */}
            <div>
              <label
                className="block text-xs font-medium mb-1"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Schema
              </label>
              <select
                value={selectedSchema}
                onChange={(e) => setSelectedSchema(e.target.value)}
                className="w-full text-xs px-2 py-1.5 rounded"
                style={{
                  backgroundColor: 'var(--color-background)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              >
                <option value="">Select schema…</option>
                {schemas.map(s => (
                  <option key={s.name} value={s.name}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>

            {/* Table name input */}
            <div>
              <label
                className="block text-xs font-medium mb-1"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Table Name
              </label>
              <input
                type="text"
                value={tableName}
                onChange={(e) => setTableName(e.target.value)}
                placeholder="e.g. clamps"
                className="w-full text-xs px-2 py-1.5 rounded"
                style={{
                  backgroundColor: 'var(--color-background)',
                  color: 'var(--color-text)',
                  border: '1px solid var(--color-border)',
                }}
              />
            </div>
          </div>

          {/* Column builder */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <label
                className="text-xs font-medium"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Columns
              </label>
              <button
                type="button"
                onClick={addColumn}
                className="text-xs px-2 py-1 rounded transition-opacity hover:opacity-80"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: 'var(--color-on-primary, #fff)',
                }}
              >
                + Add Column
              </button>
            </div>

            {/* Column header */}
            <div
              className="hidden sm:grid gap-2 mb-1 text-xs font-medium px-1"
              style={{
                gridTemplateColumns: '1fr 120px 50px 100px 32px',
                color: 'var(--color-text-muted)',
              }}
            >
              <span>Name</span>
              <span>Type</span>
              <span>Null</span>
              <span>Default</span>
              <span></span>
            </div>

            {/* Column rows */}
            <div className="space-y-2">
              {columns.map((col) => (
                <ColumnRow
                  key={col.id}
                  column={col}
                  onUpdate={updateColumn}
                  onRemove={removeColumn}
                  canRemove={columns.length > 1}
                />
              ))}
            </div>
          </div>

          {/* Include image support */}
          <label
            className="flex items-center gap-2 text-xs cursor-pointer"
            style={{ color: 'var(--color-text)' }}
          >
            <input
              type="checkbox"
              checked={includeImages}
              onChange={(e) => setIncludeImages(e.target.checked)}
              className="rounded"
              style={{ accentColor: 'var(--color-primary)' }}
            />
            <span>Include image support</span>
            <span
              className="text-xs"
              style={{ color: 'var(--color-text-muted)' }}
            >
              (auto-creates a link table for photos)
            </span>
          </label>

          {/* SQL Preview */}
          <div>
            <label
              className="block text-xs font-medium mb-1"
              style={{ color: 'var(--color-text-muted)' }}
            >
              SQL Preview
            </label>
            <pre
              className="text-xs p-3 rounded overflow-x-auto whitespace-pre font-mono"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
                maxHeight: '200px',
                overflowY: 'auto',
              }}
            >
              {sqlPreview}
            </pre>
          </div>
        </div>

        {/* Error display */}
        {error && (
          <div
            className="shrink-0 mx-4 mb-2 px-3 py-2 text-xs rounded"
            style={{
              backgroundColor: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
              color: 'var(--color-error)',
              border: '1px solid color-mix(in srgb, var(--color-error) 30%, transparent)',
            }}
          >
            {error}
          </div>
        )}

        {/* Footer */}
        <div
          className="shrink-0 flex items-center justify-end gap-2 px-4 py-3 border-t"
          style={{ borderColor: 'var(--color-border)' }}
        >
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="text-xs px-3 py-1.5 rounded transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleCreate}
            disabled={submitting}
            className="text-xs px-3 py-1.5 rounded transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
            }}
          >
            {submitting ? 'Creating…' : 'Create Table'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---- ColumnRow sub-component ----------------------------------------------

interface ColumnRowProps {
  column: ColumnDef
  onUpdate: (id: string, field: keyof ColumnDef, value: any) => void
  onRemove: (id: string) => void
  canRemove: boolean
}

function ColumnRow({ column, onUpdate, onRemove, canRemove }: ColumnRowProps) {
  return (
    <div
      className="grid gap-2 items-center px-1"
      style={{
        gridTemplateColumns: '1fr 120px 50px 100px 32px',
      }}
    >
      {/* Column name */}
      <input
        type="text"
        value={column.name}
        onChange={(e) => onUpdate(column.id, 'name', e.target.value)}
        placeholder="column_name"
        className="text-xs px-2 py-1.5 rounded"
        style={{
          backgroundColor: 'var(--color-background)',
          color: 'var(--color-text)',
          border: '1px solid var(--color-border)',
        }}
      />

      {/* Type dropdown */}
      <select
        value={column.type}
        onChange={(e) => onUpdate(column.id, 'type', e.target.value as ColumnType)}
        className="text-xs px-1 py-1.5 rounded"
        style={{
          backgroundColor: 'var(--color-background)',
          color: 'var(--color-text)',
          border: '1px solid var(--color-border)',
        }}
      >
        {COLUMN_TYPES.map(t => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </select>

      {/* Nullable checkbox */}
      <div className="flex justify-center">
        <input
          type="checkbox"
          checked={column.nullable}
          onChange={(e) => onUpdate(column.id, 'nullable', e.target.checked)}
          title="Nullable"
          style={{ accentColor: 'var(--color-primary)' }}
        />
      </div>

      {/* Default value */}
      <input
        type="text"
        value={column.defaultValue}
        onChange={(e) => onUpdate(column.id, 'defaultValue', e.target.value)}
        placeholder="default"
        className="text-xs px-2 py-1.5 rounded"
        style={{
          backgroundColor: 'var(--color-background)',
          color: 'var(--color-text)',
          border: '1px solid var(--color-border)',
        }}
      />

      {/* Remove button */}
      <button
        type="button"
        onClick={() => onRemove(column.id)}
        disabled={!canRemove}
        className="text-xs px-1 py-1 rounded transition-opacity hover:opacity-70 disabled:opacity-20"
        style={{ color: 'var(--color-text-muted)' }}
        aria-label="Remove column"
        title="Remove column"
      >
        ✕
      </button>
    </div>
  )
}
