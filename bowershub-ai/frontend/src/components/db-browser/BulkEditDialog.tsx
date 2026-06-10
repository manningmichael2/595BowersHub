/**
 * BulkEditDialog — modal dialog for applying a value to a single column
 * across all selected rows.
 *
 * Flow:
 * 1. User picks a column from a dropdown (PK, created_at, updated_at, archived_at excluded)
 * 2. SmartFieldRenderer renders for the chosen column so the user can set a value
 * 3. "Apply" calls store.bulkEdit(selectedRowIds, column, value)
 * 4. On success: closes dialog, clears selection, reloads rows
 * 5. On error: shows inline error message
 *
 * Props: { open, onClose }. Reads selectedRows + columns from the store.
 * Uses CSS custom properties for all colors.
 *
 * _Requirements: 27.5_
 */

import { useState, useMemo, useEffect, useCallback } from 'react'
import { useDbBrowserStore, type ColumnMeta } from '../../stores/db-browser'
import SmartFieldRenderer from './SmartFieldRenderer'

// ---- Props ----------------------------------------------------------------

interface BulkEditDialogProps {
  open: boolean
  onClose: () => void
}

// ---- Constants ------------------------------------------------------------

/** Columns excluded from bulk edit */
const EXCLUDED_COLUMNS = new Set(['created_at', 'updated_at', 'archived_at'])

function isEditableColumn(col: ColumnMeta): boolean {
  if (col.is_pk) return false
  if (EXCLUDED_COLUMNS.has(col.column_name)) return false
  return true
}

// ---- Component ------------------------------------------------------------

export default function BulkEditDialog({ open, onClose }: BulkEditDialogProps) {
  const columns = useDbBrowserStore(s => s.columns)
  const selectedRows = useDbBrowserStore(s => s.selectedRows)
  const bulkEdit = useDbBrowserStore(s => s.bulkEdit)
  const clearSelection = useDbBrowserStore(s => s.clearSelection)
  const loadRows = useDbBrowserStore(s => s.loadRows)
  const activeSchema = useDbBrowserStore(s => s.activeSchema)
  const activeTable = useDbBrowserStore(s => s.activeTable)

  // Local state
  const [selectedColumn, setSelectedColumn] = useState<string>('')
  const [value, setValue] = useState<any>(null)
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Editable columns (exclude PK, timestamps)
  const editableColumns = useMemo(
    () => columns.filter(isEditableColumn),
    [columns]
  )

  // The ColumnMeta for the currently selected column
  const selectedColumnMeta = useMemo(
    () => editableColumns.find(c => c.column_name === selectedColumn) ?? null,
    [editableColumns, selectedColumn]
  )

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setSelectedColumn('')
      setValue(null)
      setError(null)
      setSubmitting(false)
    }
  }, [open])

  // Handle column selection change
  const handleColumnChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setSelectedColumn(e.target.value)
    setValue(null)
    setError(null)
  }, [])

  // Handle Apply
  const handleApply = useCallback(async () => {
    if (!selectedColumn) return

    setSubmitting(true)
    setError(null)

    try {
      const rowIds = Array.from(selectedRows)
      await bulkEdit(rowIds, selectedColumn, value)
      // Success: close, clear selection, reload
      clearSelection()
      await loadRows()
      onClose()
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Failed to apply bulk edit'
      setError(message)
    } finally {
      setSubmitting(false)
    }
  }, [selectedColumn, value, selectedRows, bulkEdit, clearSelection, loadRows, onClose])

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

  if (!open) return null

  const rowCount = selectedRows.size

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="w-full max-w-md flex flex-col rounded-lg shadow-xl mx-4"
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
            Bulk Edit
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

        {/* Body */}
        <div className="flex-1 min-h-0 px-4 py-4 space-y-4">
          {/* Row count info */}
          <p
            className="text-xs"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Apply a value to{' '}
            <span className="font-semibold" style={{ color: 'var(--color-text)' }}>
              {rowCount} row{rowCount !== 1 ? 's' : ''}
            </span>
          </p>

          {/* Column picker */}
          <div className="space-y-1">
            <label
              className="text-xs font-medium"
              style={{ color: 'var(--color-text-muted)' }}
            >
              Column
            </label>
            <select
              value={selectedColumn}
              onChange={handleColumnChange}
              className="w-full text-xs px-2 py-1.5 rounded outline-none"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            >
              <option value="">Select a column…</option>
              {editableColumns.map(col => (
                <option key={col.column_name} value={col.column_name}>
                  {col.column_name}
                </option>
              ))}
            </select>
          </div>

          {/* Value editor — renders SmartFieldRenderer for the selected column */}
          {selectedColumnMeta && (
            <div>
              <SmartFieldRenderer
                column={selectedColumnMeta}
                value={value}
                onChange={setValue}
                compact={false}
                schema={activeSchema ?? undefined}
                table={activeTable ?? undefined}
              />
            </div>
          )}
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
            onClick={handleApply}
            disabled={submitting || !selectedColumn}
            className="text-xs px-3 py-1.5 rounded transition-opacity hover:opacity-80 disabled:opacity-40"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
            }}
          >
            {submitting ? 'Applying…' : `Apply to ${rowCount} row${rowCount !== 1 ? 's' : ''}`}
          </button>
        </div>
      </div>
    </div>
  )
}
