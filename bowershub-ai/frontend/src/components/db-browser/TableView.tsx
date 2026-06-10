/**
 * TableView — paginated row browser for a selected table.
 *
 * Renders a scrollable table with column headers, clickable rows that
 * navigate to DetailView, and pagination controls at the bottom.
 * Supports horizontal scroll on narrow viewports and sticky headers.
 * Includes checkbox column for row selection with shift-click range selection,
 * header checkbox for select all/none with indeterminate state, and a
 * BulkActionsToolbar when rows are selected.
 *
 * _Requirements: 3.2, 3.3, 3.4, 3.5, 23.2, 27.1, 27.2, 27.3_
 */
import { useEffect, useMemo, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDbBrowserStore } from '../../stores/db-browser'
import { useIsAdmin } from '../../hooks/useIsAdmin'
import FilterBuilder from './FilterBuilder'
import CreateRowDialog from './CreateRowDialog'
import ColumnSettings from './ColumnSettings'
import KeyboardNavigationProvider from './KeyboardNavigationProvider'
import BulkActionsToolbar from './BulkActionsToolbar'
import BulkDeleteDialog from './BulkDeleteDialog'
import BulkEditDialog from './BulkEditDialog'
import InlineCellEditor from './InlineCellEditor'
import SavedViewTabs from './SavedViewTabs'

export default function TableView() {
  const { schema, table } = useParams<{ schema: string; table: string }>()
  const navigate = useNavigate()
  const isAdmin = useIsAdmin()

  // Store state
  const rows = useDbBrowserStore(s => s.rows)
  const columns = useDbBrowserStore(s => s.columns)
  const totalRows = useDbBrowserStore(s => s.totalRows)
  const filteredRows = useDbBrowserStore(s => s.filteredRows)
  const page = useDbBrowserStore(s => s.page)
  const pageSize = useDbBrowserStore(s => s.pageSize)
  const rowsLoading = useDbBrowserStore(s => s.rowsLoading)
  const activeSchema = useDbBrowserStore(s => s.activeSchema)
  const activeTable = useDbBrowserStore(s => s.activeTable)
  const selectTable = useDbBrowserStore(s => s.selectTable)
  const setPage = useDbBrowserStore(s => s.setPage)
  const setPageSize = useDbBrowserStore(s => s.setPageSize)
  const sortColumn = useDbBrowserStore(s => s.sortColumn)
  const sortDirection = useDbBrowserStore(s => s.sortDirection)
  const setSort = useDbBrowserStore(s => s.setSort)
  const searchTerm = useDbBrowserStore(s => s.searchTerm)
  const setSearch = useDbBrowserStore(s => s.setSearch)

  // Bulk selection state (Req 27)
  const selectedRows = useDbBrowserStore(s => s.selectedRows)
  const lastSelectedRowIndex = useDbBrowserStore(s => s.lastSelectedRowIndex)
  const toggleRowSelection = useDbBrowserStore(s => s.toggleRowSelection)
  const toggleAllRows = useDbBrowserStore(s => s.toggleAllRows)
  const selectRange = useDbBrowserStore(s => s.selectRange)
  const clearSelection = useDbBrowserStore(s => s.clearSelection)

  // Inline editing state (Req 25)
  const editingCell = useDbBrowserStore(s => s.editingCell)
  const startEditing = useDbBrowserStore(s => s.startEditing)

  // Layout state for column visibility/order
  const layouts = useDbBrowserStore(s => s.layouts)
  const layoutKey = activeSchema && activeTable ? `${activeSchema}.${activeTable}` : null
  const currentLayout = layoutKey ? layouts[layoutKey] : undefined

  // Local search input state for immediate typing feedback
  const [localSearch, setLocalSearch] = useState(searchTerm)
  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // CreateRowDialog open/close state
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

  // BulkEditDialog open/close state (Req 27.5)
  const [bulkEditDialogOpen, setBulkEditDialogOpen] = useState(false)

  // Inline editing toast error state (Req 25.6)
  const [cellToast, setCellToast] = useState<{ id: number; msg: string } | null>(null)
  const handleCellError = useCallback((msg: string) => {
    const id = Date.now()
    setCellToast({ id, msg })
    setTimeout(() => setCellToast(prev => prev?.id === id ? null : prev), 4000)
  }, [])

  // Header checkbox ref for indeterminate state
  const headerCheckboxRef = useRef<HTMLInputElement>(null)

  // Search input ref for Ctrl+F keyboard shortcut (Req 26.6)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Derived: primary key column (used by selection + keyboard callbacks)
  const pkColumn = useMemo(
    () => columns.find(c => c.is_pk),
    [columns]
  )

  // Keyboard navigation: focused cell state (Req 26)
  const focusedCell = useDbBrowserStore(s => s.focusedCell)

  // Keyboard navigation callbacks (Req 26.4, 26.5, 26.7)
  const handleKbCreateRow = useCallback(() => {
    setCreateDialogOpen(true)
  }, [])

  const handleKbDuplicateRow = useCallback((rowIndex: number) => {
    if (!pkColumn || !schema || !table) return
    const row = rows[rowIndex]
    if (!row) return
    const id = row[pkColumn.column_name]
    // Navigate to detail view with duplicate flag (handled by DetailView)
    navigate(`/db/${schema}/${table}/${id}?duplicate=1`)
  }, [pkColumn, schema, table, rows, navigate])

  const [deleteConfirmRowIndex, setDeleteConfirmRowIndex] = useState<number | null>(null)

  const handleKbDeleteRow = useCallback((rowIndex: number) => {
    setDeleteConfirmRowIndex(rowIndex)
  }, [])

  const deleteRow = useDbBrowserStore(s => s.deleteRow)

  const confirmDeleteRow = useCallback(async () => {
    if (deleteConfirmRowIndex === null || !pkColumn) return
    const row = rows[deleteConfirmRowIndex]
    if (!row) return
    const id = String(row[pkColumn.column_name])
    await deleteRow(id)
    setDeleteConfirmRowIndex(null)
  }, [deleteConfirmRowIndex, pkColumn, rows, deleteRow])

  // Sync local state when store searchTerm changes externally (e.g., view switch)
  useEffect(() => {
    setLocalSearch(searchTerm)
  }, [searchTerm])

  // Debounced search: wait 300ms after the user stops typing
  const handleSearchChange = useCallback((value: string) => {
    setLocalSearch(value)
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current)
    }
    debounceTimer.current = setTimeout(() => {
      setSearch(value)
    }, 300)
  }, [setSearch])

  // Cleanup debounce timer on unmount
  useEffect(() => {
    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current)
      }
    }
  }, [])

  // Load table data when schema/table params change
  useEffect(() => {
    if (schema && table && (schema !== activeSchema || table !== activeTable)) {
      selectTable(schema, table)
    }
  }, [schema, table, activeSchema, activeTable, selectTable])

  // Compute header checkbox state (all, some, or none selected)
  const allRowIds = useMemo(() => {
    if (!pkColumn) return [] as string[]
    return rows.map(r => String(r[pkColumn.column_name]))
  }, [rows, pkColumn])

  const allSelected = allRowIds.length > 0 && allRowIds.every(id => selectedRows.has(id))
  const someSelected = !allSelected && allRowIds.some(id => selectedRows.has(id))

  // Set indeterminate state on header checkbox
  useEffect(() => {
    if (headerCheckboxRef.current) {
      headerCheckboxRef.current.indeterminate = someSelected
    }
  }, [someSelected])

  // Handle row checkbox click with shift-click range selection
  const handleRowCheckboxClick = useCallback(
    (rowId: string, rowIndex: number, event: React.MouseEvent) => {
      if (event.shiftKey && lastSelectedRowIndex !== null) {
        selectRange(lastSelectedRowIndex, rowIndex)
      } else {
        toggleRowSelection(rowId)
      }
    },
    [lastSelectedRowIndex, selectRange, toggleRowSelection]
  )

  // Bulk action callbacks (tasks 16.3, 16.4, 16.5)
  const [bulkDeleteDialogOpen, setBulkDeleteDialogOpen] = useState(false)

  const handleBulkDelete = useCallback(() => {
    setBulkDeleteDialogOpen(true)
  }, [])

  const handleBulkEdit = useCallback(() => {
    setBulkEditDialogOpen(true)
  }, [])

  // Columns filtered and ordered by layout settings (Req 11)
  const visibleColumns = useMemo(() => {
    const savedList = currentLayout?.list?.columns
    if (savedList && savedList.length > 0) {
      // Build a lookup map from saved config
      const savedMap = new Map(savedList.map(c => [c.name, c]))
      // Filter to only columns that still exist in DB
      const entries = columns
        .map(col => {
          const saved = savedMap.get(col.column_name)
          if (saved) {
            return { col, visible: saved.visible, position: saved.position }
          }
          // New column not in saved config: use default visibility rules
          const defaultHidden = new Set(['notes', 'url', 'ai_summary', 'description'])
          return {
            col,
            visible: col.is_pk || !defaultHidden.has(col.column_name),
            position: savedList.length + columns.indexOf(col),
          }
        })
        .filter(entry => entry.visible)
        .sort((a, b) => a.position - b.position)

      return entries.map(e => e.col)
    }

    // Default: hide wide columns, show rest in DB order, always show PK
    const defaultHidden = new Set(['notes', 'url', 'ai_summary', 'description'])
    return columns.filter(col => col.is_pk || !defaultHidden.has(col.column_name))
  }, [columns, currentLayout])

  // Bulk export: generate CSV from selected rows using visible columns (Req 27.6)
  const handleBulkExport = useCallback(() => {
    if (!pkColumn || !schema || !table || selectedRows.size === 0) return

    // Get selected rows from the store's rows array
    const selectedData = rows.filter(row =>
      selectedRows.has(String(row[pkColumn.column_name]))
    )
    if (selectedData.length === 0) return

    // Get visible column names for the CSV header
    const colNames = visibleColumns.map(c => c.column_name)

    // Helper: escape a CSV cell value
    const escapeCsvCell = (value: any): string => {
      if (value === null || value === undefined) return ''
      if (typeof value === 'boolean') return value ? 'true' : 'false'
      if (typeof value === 'object') {
        if (value instanceof Date) return value.toISOString()
        return JSON.stringify(value)
      }
      const str = String(value)
      // Wrap in quotes if the value contains comma, quote, or newline
      if (str.includes(',') || str.includes('"') || str.includes('\n') || str.includes('\r')) {
        return '"' + str.replace(/"/g, '""') + '"'
      }
      return str
    }

    // Build CSV content: header + data rows
    const header = colNames.map(name => escapeCsvCell(name)).join(',')
    const dataRows = selectedData.map(row =>
      colNames.map(col => escapeCsvCell(row[col])).join(',')
    )
    const csvContent = [header, ...dataRows].join('\n')

    // Create Blob and trigger download
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${schema}_${table}_export.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [pkColumn, schema, table, selectedRows, rows, visibleColumns])

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil((filteredRows || totalRows) / pageSize)),
    [filteredRows, totalRows, pageSize]
  )

  const showingStart = useMemo(
    () => rows.length === 0 ? 0 : (page - 1) * pageSize + 1,
    [page, pageSize, rows.length]
  )

  const showingEnd = useMemo(
    () => Math.min(page * pageSize, filteredRows || totalRows),
    [page, pageSize, filteredRows, totalRows]
  )

  const displayTotal = filteredRows || totalRows

  // Navigate to detail view on row click
  function handleRowClick(row: Record<string, any>) {
    if (!pkColumn || !schema || !table) return
    const id = row[pkColumn.column_name]
    if (id != null) {
      navigate(`/db/${schema}/${table}/${id}`)
    }
  }

  // Loading state
  if (rowsLoading && rows.length === 0) {
    return (
      <div
        className="flex items-center justify-center h-full"
        style={{ color: 'var(--color-text-muted)' }}
      >
        <div className="text-center">
          <div
            className="inline-block w-5 h-5 border-2 rounded-full animate-spin mb-2"
            style={{
              borderColor: 'var(--color-border)',
              borderTopColor: 'var(--color-primary)',
            }}
          />
          <p className="text-sm">Loading…</p>
        </div>
      </div>
    )
  }

  // Empty state
  if (!rowsLoading && rows.length === 0 && columns.length > 0) {
    return (
      <div
        className="flex items-center justify-center h-full"
        style={{ color: 'var(--color-text-muted)' }}
      >
        <p className="text-sm">No rows found</p>
      </div>
    )
  }

  return (
    <KeyboardNavigationProvider
      onCreateRow={isAdmin ? handleKbCreateRow : undefined}
      onDuplicateRow={isAdmin ? handleKbDuplicateRow : undefined}
      onDeleteRow={isAdmin ? handleKbDeleteRow : undefined}
      searchInputRef={searchInputRef}
    >
    <div className="flex flex-col h-full min-h-0">
      {/* Saved view tabs (Req 28) */}
      <SavedViewTabs />

      {/* Table header */}
      <div
        className="shrink-0 px-4 py-2 flex items-center justify-between border-b"
        style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-surface)',
        }}
      >
        <h2
          className="text-sm font-semibold truncate"
          style={{ color: 'var(--color-text)' }}
        >
          {schema}.{table}
        </h2>
        <div className="flex items-center gap-2">
          {/* Add Row button — touch-friendly (Req 23.4), hidden for non-admin (Req 21.3) */}
          {isAdmin && (
          <button
            type="button"
            onClick={() => setCreateDialogOpen(true)}
            className="text-xs px-3 py-2 sm:px-2 sm:py-1 rounded transition-opacity hover:opacity-80 flex items-center gap-1 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 justify-center"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
            }}
            title="Add Row"
          >
            <span className="text-sm leading-none">+</span>
            <span className="hidden sm:inline">Add Row</span>
          </button>
          )}
          {/* Search input */}
          <div className="relative flex items-center">
            <input
              ref={searchInputRef}
              type="text"
              value={localSearch}
              onChange={(e) => handleSearchChange(e.target.value)}
              placeholder="Search…"
              className="text-xs rounded px-2 py-1 pr-6 outline-none w-36 sm:w-48"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            />
            {localSearch && (
              <button
                type="button"
                onClick={() => handleSearchChange('')}
                className="absolute right-1.5 text-xs leading-none opacity-60 hover:opacity-100"
                style={{ color: 'var(--color-text-muted)' }}
                aria-label="Clear search"
              >
                ✕
              </button>
            )}
          </div>
          {/* Matched row count */}
          {searchTerm && (
            <span
              className="text-xs whitespace-nowrap"
              style={{ color: 'var(--color-text-muted)' }}
            >
              {filteredRows} of {totalRows}
            </span>
          )}
          <FilterBuilder />
          <ColumnSettings />
          {rowsLoading && (
            <div
              className="inline-block w-3.5 h-3.5 border-2 rounded-full animate-spin shrink-0"
              style={{
                borderColor: 'var(--color-border)',
                borderTopColor: 'var(--color-primary)',
              }}
            />
          )}
        </div>
      </div>

      {/* Scrollable table area — horizontal scroll enabled for mobile (Req 23.2) */}
      <div className="flex-1 min-h-0 overflow-x-auto overflow-y-auto -webkit-overflow-scrolling-touch">
        <table className="w-full text-sm border-collapse min-w-max">
          <thead
            className="sticky top-0 z-10"
            style={{ backgroundColor: 'var(--color-surface)' }}
          >
            <tr
              style={{ borderBottom: '1px solid var(--color-border)' }}
            >
              {/* Checkbox column header — select all / none (Req 23.4: 44x44 touch target on mobile) */}
              <th
                className="w-10 sm:w-10 px-2 py-1 sm:py-2 text-center"
                style={{ color: 'var(--color-text-muted)' }}
              >
                <label className="inline-flex items-center justify-center w-11 h-11 sm:w-auto sm:h-auto cursor-pointer">
                  <input
                    ref={headerCheckboxRef}
                    type="checkbox"
                    checked={allSelected}
                    onChange={() => toggleAllRows()}
                    className="w-4 h-4 cursor-pointer accent-[var(--color-primary)]"
                    title={allSelected ? 'Deselect all' : 'Select all'}
                    aria-label={allSelected ? 'Deselect all rows' : 'Select all rows'}
                  />
                </label>
              </th>
              {visibleColumns.map(col => (
                <th
                  key={col.column_name}
                  className="text-left px-2 sm:px-3 py-1 sm:py-2 font-medium whitespace-nowrap cursor-pointer select-none"
                  style={{ color: 'var(--color-text-muted)' }}
                  onClick={() => setSort(col.column_name)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor = 'var(--color-row-hover, rgba(128,128,128,0.08))'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  <span className="inline-flex items-center gap-1">
                    {col.column_name}
                    {sortColumn === col.column_name && sortDirection === 'asc' && (
                      <span aria-label="sorted ascending">▲</span>
                    )}
                    {sortColumn === col.column_name && sortDirection === 'desc' && (
                      <span aria-label="sorted descending">▼</span>
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, rowIndex) => {
              const rowKey = pkColumn
                ? String(row[pkColumn.column_name])
                : String(rowIndex)

              const isSelected = selectedRows.has(rowKey)

              return (
                <tr
                  key={rowKey}
                  onClick={() => handleRowClick(row)}
                  className="cursor-pointer transition-colors"
                  style={{
                    backgroundColor: isSelected
                      ? 'var(--color-row-selected, color-mix(in srgb, var(--color-primary) 12%, transparent))'
                      : rowIndex % 2 === 0
                        ? 'transparent'
                        : 'var(--color-row-alt, rgba(128,128,128,0.04))',
                    borderBottom: '1px solid var(--color-border)',
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) {
                      e.currentTarget.style.backgroundColor = 'var(--color-row-hover, rgba(128,128,128,0.08))'
                    }
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = isSelected
                      ? 'var(--color-row-selected, color-mix(in srgb, var(--color-primary) 12%, transparent))'
                      : rowIndex % 2 === 0
                        ? 'transparent'
                        : 'var(--color-row-alt, rgba(128,128,128,0.04))'
                  }}
                >
                  {/* Selection checkbox — 44x44 touch target on mobile (Req 23.4) */}
                  <td
                    className="w-10 sm:w-10 px-2 py-0.5 sm:py-1.5 text-center"
                    onClick={(e) => e.stopPropagation()}
                  >
                    <label className="inline-flex items-center justify-center w-11 h-11 sm:w-auto sm:h-auto cursor-pointer">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onClick={(e) => handleRowCheckboxClick(rowKey, rowIndex, e as unknown as React.MouseEvent)}
                        onChange={() => {/* handled by onClick for shift-click support */}}
                        className="w-4 h-4 cursor-pointer accent-[var(--color-primary)]"
                        aria-label={`Select row ${rowKey}`}
                      />
                    </label>
                  </td>
                  {visibleColumns.map((col, colIndex) => {
                    // Determine if this cell is being inline-edited
                    // Store's editingCell.col refers to index in editable columns (non-PK)
                    const editableCols = columns.filter(c => !c.is_pk)
                    const editableColIndex = editableCols.findIndex(c => c.column_name === col.column_name)
                    const isEditing = editingCell !== null
                      && editingCell.row === rowIndex
                      && editableColIndex >= 0
                      && editingCell.col === editableColIndex

                    const isEditable = !col.is_pk && col.column_name !== 'created_at' && col.column_name !== 'updated_at'

                    // Keyboard focus indicator (Req 26.1)
                    const isFocused = focusedCell !== null
                      && focusedCell.row === rowIndex
                      && editableColIndex >= 0
                      && focusedCell.col === editableColIndex

                    return (
                      <td
                        key={col.column_name}
                        className="px-2 sm:px-3 py-0.5 sm:py-1.5 whitespace-nowrap max-w-[300px] truncate"
                        style={{ color: 'var(--color-text)' }}
                        title={!isEditing ? formatCellValue(row[col.column_name]) : undefined}
                        data-kb-focused={isFocused ? 'true' : undefined}
                        onClick={(e) => {
                          if (isAdmin && isEditable && editableColIndex >= 0) {
                            e.stopPropagation()
                            startEditing(rowIndex, editableColIndex)
                          }
                        }}
                      >
                        {isEditing && pkColumn ? (
                          <InlineCellEditor
                            rowIndex={rowIndex}
                            column={col}
                            originalValue={row[col.column_name]}
                            rowId={String(row[pkColumn.column_name])}
                            onError={handleCellError}
                          />
                        ) : (
                          formatCellValue(row[col.column_name])
                        )}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination controls — fixed at bottom */}
      <div
        className="shrink-0 px-4 py-2 flex items-center justify-between gap-3 border-t flex-wrap"
        style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-surface)',
        }}
      >
        {/* Row count display */}
        <span
          className="text-xs whitespace-nowrap"
          style={{ color: 'var(--color-text-muted)' }}
        >
          Showing {showingStart}–{showingEnd} of {displayTotal} rows
        </span>

        {/* Page navigation + page size */}
        <div className="flex items-center gap-2">
          {/* Page size selector */}
          <select
            value={pageSize}
            onChange={(e) => setPageSize(Number(e.target.value))}
            className="text-xs rounded px-2 py-1 outline-none"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>

          {/* Previous button — touch-friendly on mobile (Req 23.4) */}
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
            className="text-xs px-3 py-2 sm:px-2 sm:py-1 rounded disabled:opacity-40 transition-opacity min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            ← Prev
          </button>

          {/* Page indicator */}
          <span
            className="text-xs whitespace-nowrap"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {page} / {totalPages}
          </span>

          {/* Next button — touch-friendly on mobile (Req 23.4) */}
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage(page + 1)}
            className="text-xs px-3 py-2 sm:px-2 sm:py-1 rounded disabled:opacity-40 transition-opacity min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
          >
            Next →
          </button>
        </div>
      </div>

      {/* CreateRowDialog */}
      {schema && table && (
        <CreateRowDialog
          open={createDialogOpen}
          onClose={() => setCreateDialogOpen(false)}
          schema={schema}
          table={table}
        />
      )}

      {/* Bulk Actions Toolbar — shown when rows selected, hidden for non-admin (Req 21.3) */}
      {isAdmin && (
      <BulkActionsToolbar
        onBulkDelete={handleBulkDelete}
        onBulkEdit={handleBulkEdit}
        onBulkExport={handleBulkExport}
      />
      )}

      {/* Bulk Delete confirmation dialog (Req 27.4) */}
      <BulkDeleteDialog
        open={bulkDeleteDialogOpen}
        onClose={() => setBulkDeleteDialogOpen(false)}
      />

      {/* Bulk Edit dialog (Req 27.5) */}
      <BulkEditDialog
        open={bulkEditDialogOpen}
        onClose={() => setBulkEditDialogOpen(false)}
      />

      {/* Inline edit error toast (Req 25.6) */}
      {cellToast && (
        <div className="fixed bottom-4 right-4 z-50 animate-[fadeIn_0.2s_ease-in]">
          <div
            className="rounded-lg border px-3 py-2 text-sm shadow-lg max-w-sm"
            style={{
              backgroundColor: 'var(--color-surface)',
              borderColor: 'color-mix(in srgb, var(--color-error) 40%, transparent)',
              color: 'var(--color-text)',
            }}
            role="alert"
          >
            <span style={{ color: 'var(--color-error)' }} className="mr-1">⚠</span>
            {cellToast.msg}
          </div>
        </div>
      )}

      {/* Delete confirmation dialog (Req 26.7) */}
      {deleteConfirmRowIndex !== null && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ backgroundColor: 'rgba(0,0,0,0.5)' }}
          onClick={() => setDeleteConfirmRowIndex(null)}
        >
          <div
            className="rounded-lg p-5 max-w-sm w-full mx-4 shadow-xl"
            style={{ backgroundColor: 'var(--color-surface)', color: 'var(--color-text)' }}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-semibold mb-2">Delete Row?</h3>
            <p className="text-xs mb-4" style={{ color: 'var(--color-text-muted)' }}>
              This action cannot be undone. Are you sure you want to delete this row?
            </p>
            <div className="flex gap-2 justify-end">
              <button
                type="button"
                onClick={() => setDeleteConfirmRowIndex(null)}
                className="text-xs px-3 py-1.5 rounded"
                style={{ border: '1px solid var(--color-border)', color: 'var(--color-text)' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={confirmDeleteRow}
                className="text-xs px-3 py-1.5 rounded"
                style={{ backgroundColor: 'var(--color-error)', color: 'var(--color-on-primary)' }}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
    </KeyboardNavigationProvider>
  )
}

// ---- Helpers --------------------------------------------------------------

/**
 * Format a cell value for display. Handles null, booleans, dates, objects.
 */
function formatCellValue(value: any): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'object') {
    if (value instanceof Date) return value.toLocaleDateString()
    return JSON.stringify(value)
  }
  return String(value)
}
