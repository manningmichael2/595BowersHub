/**
 * useKeyboardNavigation — hook for keyboard-driven grid navigation in the DB browser.
 *
 * Reads `focusedCell` and `editingCell` from the Zustand store and attaches a
 * `keydown` listener that handles:
 *   - Arrow keys: move focus within grid bounds (only when not editing)
 *   - Enter: activate inline editing on the focused cell
 *   - Tab / Shift+Tab: move to next/previous editable cell, wrapping at row boundaries
 *   - Ctrl+N: open CreateRowDialog
 *   - Ctrl+D: duplicate the focused row
 *   - Ctrl+F: focus the search input
 *   - Delete: open deletion confirmation for the focused row
 *
 * Editable cell detection: columns that are NOT primary key and NOT timestamp
 * fields (created_at, updated_at, archived_at) are considered editable.
 *
 * _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7_
 */
import { useEffect, useCallback, useMemo } from 'react'
import { useDbBrowserStore, type ColumnMeta } from '../stores/db-browser'

/** Columns that should not be editable via keyboard navigation */
const NON_EDITABLE_NAMES = new Set([
  'created_at',
  'updated_at',
  'archived_at',
])

/** Determine if a column is editable (not PK, not a timestamp) */
function isEditableColumn(col: ColumnMeta): boolean {
  if (col.is_pk) return false
  if (NON_EDITABLE_NAMES.has(col.column_name)) return false
  return true
}

export interface KeyboardNavigationCallbacks {
  /** Called when Ctrl+N is pressed — should open the CreateRowDialog */
  onCreateRow?: () => void
  /** Called when Ctrl+D is pressed — should duplicate the focused row */
  onDuplicateRow?: (rowIndex: number) => void
  /** Called when Delete is pressed — should open delete confirmation for the focused row */
  onDeleteRow?: (rowIndex: number) => void
  /** Ref to the search input element, for Ctrl+F focus */
  searchInputRef?: React.RefObject<HTMLInputElement | null>
}

export function useKeyboardNavigation(callbacks: KeyboardNavigationCallbacks = {}) {
  const focusedCell = useDbBrowserStore(s => s.focusedCell)
  const editingCell = useDbBrowserStore(s => s.editingCell)
  const columns = useDbBrowserStore(s => s.columns)
  const rows = useDbBrowserStore(s => s.rows)
  const moveFocus = useDbBrowserStore(s => s.moveFocus)
  const moveFocusTab = useDbBrowserStore(s => s.moveFocusTab)
  const startEditing = useDbBrowserStore(s => s.startEditing)
  const setFocusedCell = useDbBrowserStore(s => s.setFocusedCell)

  /** Get only editable columns (used for Tab navigation and column index mapping) */
  const editableColumns = useMemo(
    () => columns.filter(isEditableColumn),
    [columns]
  )

  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // If we're currently editing a cell, let the inline editor handle keys
    if (editingCell) return

    // If the event target is an input/textarea/select (e.g. search box),
    // don't intercept unless it's a Ctrl shortcut
    const target = e.target as HTMLElement
    const isFormElement =
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable
    if (isFormElement && !e.ctrlKey && !e.metaKey) return

    // --- Ctrl/Meta shortcuts (work regardless of focus state) ---
    if (e.ctrlKey || e.metaKey) {
      switch (e.key.toLowerCase()) {
        case 'n':
          e.preventDefault()
          callbacks.onCreateRow?.()
          return
        case 'd':
          e.preventDefault()
          if (focusedCell) {
            callbacks.onDuplicateRow?.(focusedCell.row)
          }
          return
        case 'f':
          e.preventDefault()
          callbacks.searchInputRef?.current?.focus()
          return
      }
      return
    }

    // --- Navigation keys (require a focused cell) ---
    if (!focusedCell) {
      // If no cell is focused and user presses an arrow key, focus the first cell
      if (['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
        if (rows.length > 0 && editableColumns.length > 0) {
          e.preventDefault()
          setFocusedCell({ row: 0, col: 0 })
        }
      }
      return
    }

    switch (e.key) {
      case 'ArrowUp':
        e.preventDefault()
        moveFocus('up')
        break
      case 'ArrowDown':
        e.preventDefault()
        moveFocus('down')
        break
      case 'ArrowLeft':
        e.preventDefault()
        moveFocus('left')
        break
      case 'ArrowRight':
        e.preventDefault()
        moveFocus('right')
        break
      case 'Enter':
        e.preventDefault()
        startEditing(focusedCell.row, focusedCell.col)
        break
      case 'Tab':
        e.preventDefault()
        moveFocusTab(e.shiftKey)
        break
      case 'Delete':
      case 'Backspace':
        // Only Delete (not Backspace) triggers row deletion
        if (e.key === 'Delete') {
          e.preventDefault()
          callbacks.onDeleteRow?.(focusedCell.row)
        }
        break
      case 'Escape':
        e.preventDefault()
        setFocusedCell(null)
        break
    }
  }, [
    editingCell,
    focusedCell,
    rows.length,
    editableColumns.length,
    moveFocus,
    moveFocusTab,
    startEditing,
    setFocusedCell,
    callbacks,
  ])

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  return {
    focusedCell,
    editingCell,
    editableColumns,
    isEditableColumn,
  }
}

export default useKeyboardNavigation
