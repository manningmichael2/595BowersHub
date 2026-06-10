/**
 * CreateRowDialog — modal dialog for creating a new row in the active table.
 *
 * Renders a centered overlay with a form using SmartFieldRenderer for each
 * editable column. Pre-populates fields with column defaults where defined.
 * On successful creation, navigates to the DetailView for the new row.
 *
 * _Requirements: 12.1, 12.2, 12.5_
 */

import { useState, useMemo, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDbBrowserStore, type ColumnMeta } from '../../stores/db-browser'
import { useIsAdmin } from '../../hooks/useIsAdmin'
import SmartFieldRenderer from './SmartFieldRenderer'

// ---- Props ----------------------------------------------------------------

interface CreateRowDialogProps {
  open: boolean
  onClose: () => void
  schema: string
  table: string
  /** Optional pre-filled values (used by Duplicate feature) */
  initialValues?: Record<string, any>
  /** Optional set of column names that should be read-only (used by Add from relations) */
  readOnlyFields?: Set<string>
}

// ---- Constants ------------------------------------------------------------

/** Columns that are excluded from the creation form */
const EXCLUDED_SUFFIXES = ['created_at', 'updated_at', 'archived_at']

function isExcludedColumn(col: ColumnMeta): boolean {
  if (col.is_pk) return true
  return EXCLUDED_SUFFIXES.includes(col.column_name)
}

// ---- Helpers: parse Postgres column_default string -------------------------

/**
 * Parse a Postgres column_default string into a usable JS value.
 *
 * Examples of column_default values from Postgres:
 *   - "'excellent'::text"        → "excellent"
 *   - "'active'::character varying" → "active"
 *   - "0"                        → 0
 *   - "0.0"                      → 0
 *   - "true"                     → true
 *   - "false"                    → false
 *   - "now()"                    → null (skip — handled by DB)
 *   - "gen_random_uuid()"        → null (skip — handled by DB)
 *   - "nextval('...')"           → null (skip — sequence)
 *   - "NULL::text"               → null
 */
function parseColumnDefault(defaultStr: string | null, dataType: string): any {
  if (!defaultStr) return null

  const val = defaultStr.trim()

  // Skip function calls (now(), gen_random_uuid(), nextval(...), etc.)
  if (val.includes('(') && val.includes(')')) return null

  // Skip explicit NULL casts
  if (val.toUpperCase().startsWith('NULL')) return null

  // Handle string literals: 'value'::type or just 'value'
  const stringMatch = val.match(/^'(.*?)'(?:::.*)?$/)
  if (stringMatch) {
    return stringMatch[1]
  }

  // Handle boolean
  if (val === 'true') return true
  if (val === 'false') return false

  // Handle numeric values (may have ::type suffix)
  const numericStr = val.replace(/::.*$/, '').trim()
  const num = Number(numericStr)
  if (!isNaN(num) && numericStr !== '') return num

  return null
}

// ---- Component ------------------------------------------------------------

export default function CreateRowDialog({
  open,
  onClose,
  schema,
  table,
  initialValues,
  readOnlyFields,
}: CreateRowDialogProps) {
  const navigate = useNavigate()
  const isAdmin = useIsAdmin()
  const columns = useDbBrowserStore(s => s.columns)
  const createRow = useDbBrowserStore(s => s.createRow)

  // Editable columns (exclude PK, timestamps)
  const editableColumns = useMemo(
    () => columns.filter(col => !isExcludedColumn(col)),
    [columns]
  )

  // Build initial form values from column defaults or initialValues
  const defaultFormValues = useMemo(() => {
    const vals: Record<string, any> = {}
    for (const col of editableColumns) {
      if (initialValues && col.column_name in initialValues) {
        vals[col.column_name] = initialValues[col.column_name]
      } else {
        const parsed = parseColumnDefault(col.column_default, col.data_type)
        vals[col.column_name] = parsed ?? null
      }
    }
    return vals
  }, [editableColumns, initialValues])

  // Form state
  const [formValues, setFormValues] = useState<Record<string, any>>(defaultFormValues)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset form when dialog opens or default values change
  useEffect(() => {
    if (open) {
      setFormValues(defaultFormValues)
      setError(null)
      setSubmitting(false)
    }
  }, [open, defaultFormValues])

  // Field change handler
  const handleFieldChange = useCallback((columnName: string, value: any) => {
    setFormValues(prev => ({ ...prev, [columnName]: value }))
  }, [])

  // Submit handler
  const handleCreate = useCallback(async () => {
    setSubmitting(true)
    setError(null)

    try {
      // Filter out null values for nullable columns to let DB handle defaults
      const payload: Record<string, any> = {}
      for (const col of editableColumns) {
        const val = formValues[col.column_name]
        if (val !== null && val !== undefined && val !== '') {
          payload[col.column_name] = val
        }
      }

      const result = await createRow(payload)
      if (result) {
        // Find the PK column to get the new row's ID
        const pkCol = columns.find(c => c.is_pk)
        if (pkCol && result[pkCol.column_name] != null) {
          const newId = result[pkCol.column_name]
          onClose()
          navigate(`/db/${schema}/${table}/${newId}`)
        } else {
          // No PK in response — just close
          onClose()
        }
      }
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Failed to create row'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }, [editableColumns, formValues, createRow, columns, schema, table, navigate, onClose])

  // Close on Escape key
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
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
        // Close on backdrop click
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-2xl max-h-[85vh] flex flex-col rounded-lg shadow-xl mx-4"
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
            Add Row — {schema}.{table}
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

        {/* Form body — scrollable */}
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3">
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {editableColumns.map(col => (
              <div
                key={col.column_name}
                className={col.column_name === 'notes' ? 'sm:col-span-2' : ''}
              >
                <SmartFieldRenderer
                  column={col}
                  value={formValues[col.column_name] ?? null}
                  onChange={(val) => handleFieldChange(col.column_name, val)}
                  schema={schema}
                  table={table}
                  readOnly={readOnlyFields?.has(col.column_name)}
                />
              </div>
            ))}
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

        {/* Footer with action buttons */}
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
            {submitting ? 'Creating…' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  )
}
