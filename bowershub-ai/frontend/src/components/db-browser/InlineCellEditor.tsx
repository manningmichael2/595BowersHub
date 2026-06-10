/**
 * InlineCellEditor — mounts SmartFieldRenderer in compact mode within a table cell.
 *
 * Behavior:
 * - On blur: save via `saveCellValue`
 * - On Enter: save + move focus down (`moveFocus('down')`)
 * - On Tab: save + move to next editable cell (`moveFocusTab()`)
 * - On Escape: `stopEditing()` without saving
 * - On save failure: revert value + show toast error
 *
 * _Requirements: 25.1, 25.2, 25.3, 25.4, 25.5, 25.6_
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useDbBrowserStore, type ColumnMeta } from '../../stores/db-browser'
import SmartFieldRenderer from './SmartFieldRenderer'

export interface InlineCellEditorProps {
  /** Row index in the current rows array */
  rowIndex: number
  /** Column metadata */
  column: ColumnMeta
  /** Original value of the cell (for revert on failure) */
  originalValue: any
  /** Primary key value for the row being edited */
  rowId: string
  /** Callback to show toast error on save failure */
  onError: (message: string) => void
}

export default function InlineCellEditor({
  rowIndex,
  column,
  originalValue,
  rowId,
  onError,
}: InlineCellEditorProps) {
  const [localValue, setLocalValue] = useState(originalValue)
  const saveCellValue = useDbBrowserStore(s => s.saveCellValue)
  const stopEditing = useDbBrowserStore(s => s.stopEditing)
  const moveFocus = useDbBrowserStore(s => s.moveFocus)
  const moveFocusTab = useDbBrowserStore(s => s.moveFocusTab)
  const startEditing = useDbBrowserStore(s => s.startEditing)

  const containerRef = useRef<HTMLDivElement>(null)
  const savingRef = useRef(false)
  const savedByKeyRef = useRef(false)

  // Focus the input inside the container on mount
  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    // Small delay to allow the SmartFieldRenderer to mount its input
    const timer = setTimeout(() => {
      const input = el.querySelector('input, select, textarea') as HTMLElement | null
      if (input) {
        input.focus()
      }
    }, 10)
    return () => clearTimeout(timer)
  }, [])

  const handleSave = useCallback(async (nextAction?: 'down' | 'tab' | 'tab-reverse') => {
    if (savingRef.current) return
    savingRef.current = true

    // Only PATCH if value actually changed
    const changed = localValue !== originalValue
    try {
      if (changed) {
        await saveCellValue(rowId, column.column_name, localValue)
      } else {
        stopEditing()
      }

      // Move focus after successful save
      if (nextAction === 'down') {
        moveFocus('down')
        // Re-enter editing mode on the new focused cell
        const { focusedCell } = useDbBrowserStore.getState()
        if (focusedCell) {
          startEditing(focusedCell.row, focusedCell.col)
        }
      } else if (nextAction === 'tab') {
        moveFocusTab(false)
        const { focusedCell } = useDbBrowserStore.getState()
        if (focusedCell) {
          startEditing(focusedCell.row, focusedCell.col)
        }
      } else if (nextAction === 'tab-reverse') {
        moveFocusTab(true)
        const { focusedCell } = useDbBrowserStore.getState()
        if (focusedCell) {
          startEditing(focusedCell.row, focusedCell.col)
        }
      }
    } catch (err: any) {
      // Revert value on constraint violation and show toast
      setLocalValue(originalValue)
      const msg = err?.response?.data?.detail || err?.message || 'Failed to save cell value'
      onError(msg)
      stopEditing()
    } finally {
      savingRef.current = false
    }
  }, [localValue, originalValue, rowId, column.column_name, saveCellValue, stopEditing, moveFocus, moveFocusTab, startEditing, onError])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      stopEditing()
      return
    }

    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      e.stopPropagation()
      savedByKeyRef.current = true
      handleSave('down')
      return
    }

    if (e.key === 'Tab') {
      e.preventDefault()
      e.stopPropagation()
      savedByKeyRef.current = true
      handleSave(e.shiftKey ? 'tab-reverse' : 'tab')
      return
    }
  }, [handleSave, stopEditing])

  const handleBlur = useCallback((e: React.FocusEvent) => {
    // Don't save on blur if save was already triggered by a key action
    if (savedByKeyRef.current) return

    // Check if focus is moving to another element within the same editor
    const container = containerRef.current
    if (container && e.relatedTarget && container.contains(e.relatedTarget as Node)) {
      return
    }

    handleSave()
  }, [handleSave])

  return (
    <div
      ref={containerRef}
      className="inline-cell-editor w-full"
      onKeyDown={handleKeyDown}
      onBlur={handleBlur}
      style={{
        minWidth: '80px',
      }}
    >
      <SmartFieldRenderer
        column={column}
        value={localValue}
        onChange={setLocalValue}
        compact
      />
    </div>
  )
}
