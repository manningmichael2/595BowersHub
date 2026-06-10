/**
 * useKeyboardNavigation — unit tests.
 *
 * Tests verify the core keyboard navigation behaviors:
 * - Arrow keys move focus within grid bounds
 * - Enter activates editing on focused cell
 * - Tab/Shift+Tab wraps at row boundaries
 * - Ctrl+N opens CreateRowDialog
 * - Ctrl+D duplicates focused row
 * - Ctrl+F focuses search input
 * - Delete opens deletion confirmation
 * - Keys are ignored while editing
 * - Editable cell detection excludes PK and timestamps
 *
 * Validates: Requirements 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useKeyboardNavigation } from '../useKeyboardNavigation'

// Mock the db-browser store
const mockState = {
  focusedCell: null as { row: number; col: number } | null,
  editingCell: null as { row: number; col: number } | null,
  columns: [
    { column_name: 'id', data_type: 'integer', is_nullable: 'NO', column_default: null, is_pk: true },
    { column_name: 'name', data_type: 'text', is_nullable: 'YES', column_default: null, is_pk: false },
    { column_name: 'value', data_type: 'numeric', is_nullable: 'YES', column_default: null, is_pk: false },
    { column_name: 'created_at', data_type: 'timestamptz', is_nullable: 'NO', column_default: 'now()', is_pk: false },
    { column_name: 'updated_at', data_type: 'timestamptz', is_nullable: 'NO', column_default: 'now()', is_pk: false },
  ],
  rows: [
    { id: 1, name: 'Row 1', value: 10, created_at: '2024-01-01', updated_at: '2024-01-01' },
    { id: 2, name: 'Row 2', value: 20, created_at: '2024-01-01', updated_at: '2024-01-01' },
    { id: 3, name: 'Row 3', value: 30, created_at: '2024-01-01', updated_at: '2024-01-01' },
  ],
  moveFocus: vi.fn(),
  moveFocusTab: vi.fn(),
  startEditing: vi.fn(),
  setFocusedCell: vi.fn(),
}

vi.mock('../../stores/db-browser', () => ({
  useDbBrowserStore: (selector: (s: any) => any) => selector(mockState),
}))

function fireKeyDown(key: string, opts: Partial<KeyboardEventInit> = {}) {
  const event = new KeyboardEvent('keydown', {
    key,
    bubbles: true,
    cancelable: true,
    ...opts,
  })
  document.dispatchEvent(event)
  return event
}

describe('useKeyboardNavigation', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockState.focusedCell = null
    mockState.editingCell = null
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('Arrow key navigation (Req 26.1)', () => {
    it('moves focus up when ArrowUp is pressed', () => {
      mockState.focusedCell = { row: 1, col: 0 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('ArrowUp') })
      expect(mockState.moveFocus).toHaveBeenCalledWith('up')
      unmount()
    })

    it('moves focus down when ArrowDown is pressed', () => {
      mockState.focusedCell = { row: 0, col: 0 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('ArrowDown') })
      expect(mockState.moveFocus).toHaveBeenCalledWith('down')
      unmount()
    })

    it('moves focus left when ArrowLeft is pressed', () => {
      mockState.focusedCell = { row: 0, col: 1 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('ArrowLeft') })
      expect(mockState.moveFocus).toHaveBeenCalledWith('left')
      unmount()
    })

    it('moves focus right when ArrowRight is pressed', () => {
      mockState.focusedCell = { row: 0, col: 0 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('ArrowRight') })
      expect(mockState.moveFocus).toHaveBeenCalledWith('right')
      unmount()
    })

    it('focuses first cell when arrow key pressed and no cell focused', () => {
      mockState.focusedCell = null
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('ArrowDown') })
      expect(mockState.setFocusedCell).toHaveBeenCalledWith({ row: 0, col: 0 })
      unmount()
    })

    it('does NOT move focus when in edit mode', () => {
      mockState.focusedCell = { row: 0, col: 0 }
      mockState.editingCell = { row: 0, col: 0 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('ArrowDown') })
      expect(mockState.moveFocus).not.toHaveBeenCalled()
      unmount()
    })
  })

  describe('Enter to edit (Req 26.3)', () => {
    it('activates editing on the focused cell when Enter is pressed', () => {
      mockState.focusedCell = { row: 1, col: 0 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('Enter') })
      expect(mockState.startEditing).toHaveBeenCalledWith(1, 0)
      unmount()
    })
  })

  describe('Tab navigation (Req 26.2)', () => {
    it('calls moveFocusTab(false) on Tab', () => {
      mockState.focusedCell = { row: 0, col: 0 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('Tab') })
      expect(mockState.moveFocusTab).toHaveBeenCalledWith(false)
      unmount()
    })

    it('calls moveFocusTab(true) on Shift+Tab', () => {
      mockState.focusedCell = { row: 0, col: 1 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('Tab', { shiftKey: true }) })
      expect(mockState.moveFocusTab).toHaveBeenCalledWith(true)
      unmount()
    })
  })

  describe('Ctrl shortcuts (Req 26.4, 26.5, 26.6)', () => {
    it('Ctrl+N calls onCreateRow', () => {
      const onCreateRow = vi.fn()
      const { unmount } = renderHook(() => useKeyboardNavigation({ onCreateRow }))
      act(() => { fireKeyDown('n', { ctrlKey: true }) })
      expect(onCreateRow).toHaveBeenCalled()
      unmount()
    })

    it('Ctrl+D calls onDuplicateRow with the focused row index', () => {
      mockState.focusedCell = { row: 2, col: 0 }
      const onDuplicateRow = vi.fn()
      const { unmount } = renderHook(() => useKeyboardNavigation({ onDuplicateRow }))
      act(() => { fireKeyDown('d', { ctrlKey: true }) })
      expect(onDuplicateRow).toHaveBeenCalledWith(2)
      unmount()
    })

    it('Ctrl+F focuses the search input', () => {
      const input = document.createElement('input')
      const focusSpy = vi.spyOn(input, 'focus')
      const searchInputRef = { current: input }
      const { unmount } = renderHook(() => useKeyboardNavigation({ searchInputRef }))
      act(() => { fireKeyDown('f', { ctrlKey: true }) })
      expect(focusSpy).toHaveBeenCalled()
      unmount()
    })
  })

  describe('Delete key (Req 26.7)', () => {
    it('calls onDeleteRow with the focused row index when Delete is pressed', () => {
      mockState.focusedCell = { row: 1, col: 0 }
      const onDeleteRow = vi.fn()
      const { unmount } = renderHook(() => useKeyboardNavigation({ onDeleteRow }))
      act(() => { fireKeyDown('Delete') })
      expect(onDeleteRow).toHaveBeenCalledWith(1)
      unmount()
    })

    it('does NOT trigger delete on Backspace', () => {
      mockState.focusedCell = { row: 1, col: 0 }
      const onDeleteRow = vi.fn()
      const { unmount } = renderHook(() => useKeyboardNavigation({ onDeleteRow }))
      act(() => { fireKeyDown('Backspace') })
      expect(onDeleteRow).not.toHaveBeenCalled()
      unmount()
    })
  })

  describe('Escape (clears focus)', () => {
    it('clears focused cell when Escape is pressed', () => {
      mockState.focusedCell = { row: 0, col: 0 }
      const { unmount } = renderHook(() => useKeyboardNavigation())
      act(() => { fireKeyDown('Escape') })
      expect(mockState.setFocusedCell).toHaveBeenCalledWith(null)
      unmount()
    })
  })

  describe('Editable column detection', () => {
    it('returns editableColumns excluding PK and timestamps', () => {
      const { result, unmount } = renderHook(() => useKeyboardNavigation())
      const names = result.current.editableColumns.map(c => c.column_name)
      expect(names).toEqual(['name', 'value'])
      expect(names).not.toContain('id')
      expect(names).not.toContain('created_at')
      expect(names).not.toContain('updated_at')
      unmount()
    })
  })
})
