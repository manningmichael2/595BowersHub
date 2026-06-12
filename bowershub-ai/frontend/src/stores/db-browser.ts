/**
 * Zustand store for the native DB Browser feature.
 *
 * Manages all state for schema navigation, table browsing (pagination, sort,
 * filter, search), row detail editing, inline cell editing, keyboard navigation,
 * bulk operations, saved views, undo/redo, and field hints.
 */

import { create } from 'zustand'
import { z } from 'zod'
import { api } from '../services/api'
import { parseLoose } from '../lib/validate'
import {
  SchemaInfoSchema,
  ColumnMetaSchema,
  FieldHintSchema,
  SavedViewSchema,
  UndoEntrySchema,
  ImportResultSchema,
  RelationGroupSchema,
  RowsResponseSchema,
  type SchemaInfo,
  type TableInfo,
  type ColumnMeta,
  type FieldHint,
  type FilterCondition,
  type LayoutConfig,
  type SavedView,
  type UndoEntry,
  type RelationGroup,
  type ImportResult,
} from '../schemas/db-browser'

// Re-exported so existing call sites keep working
export type {
  SchemaInfo,
  TableInfo,
  ColumnMeta,
  FieldHint,
  FilterCondition,
  LayoutConfig,
  SavedView,
  UndoEntry,
  RelationGroup,
  ImportResult,
}

// ---- State shape ----------------------------------------------------------

interface DbBrowserState {
  // Schema tree
  schemas: SchemaInfo[]
  schemasLoading: boolean

  // Active table
  activeSchema: string | null
  activeTable: string | null
  columns: ColumnMeta[]

  // Rows
  rows: Record<string, any>[]
  totalRows: number
  filteredRows: number
  page: number
  pageSize: number
  sortColumn: string | null
  sortDirection: 'asc' | 'desc' | null
  filters: FilterCondition[]
  searchTerm: string
  rowsLoading: boolean

  // Detail view
  activeRow: Record<string, any> | null
  dirtyFields: Set<string>

  // Layout
  layouts: Record<string, LayoutConfig>

  // Field hints (cached globally)
  fieldHints: Record<string, FieldHint>

  // Inline editing (Req 25)
  editingCell: { row: number; col: number } | null

  // Keyboard navigation (Req 26)
  focusedCell: { row: number; col: number } | null

  // Bulk selection (Req 27)
  selectedRows: Set<string>
  lastSelectedRowIndex: number | null

  // Saved views (Req 28)
  views: SavedView[]
  activeViewId: string | null

  // Undo/Redo (Req 29)
  undoStack: UndoEntry[]
  redoStack: UndoEntry[]
  sessionId: string | null

  // Core actions
  loadSchemas: () => Promise<void>
  selectTable: (schema: string, table: string) => Promise<void>
  loadRows: () => Promise<void>
  setPage: (page: number) => void
  setPageSize: (size: number) => void
  setSort: (column: string) => void
  setFilters: (filters: FilterCondition[]) => void
  setSearch: (term: string) => void

  // Detail actions
  loadRow: (id: string) => Promise<void>
  saveRow: (updates: Record<string, any>) => Promise<void>
  createRow: (values: Record<string, any>) => Promise<any>
  deleteRow: (id: string) => Promise<void>

  // Field hints
  loadFieldHints: () => Promise<void>

  // Layout
  saveLayout: (schema: string, table: string, config: LayoutConfig) => Promise<void>
  loadLayout: (schema: string, table: string) => Promise<void>

  // Inline editing actions
  startEditing: (row: number, col: number) => void
  stopEditing: () => void
  saveCellValue: (rowId: string, column: string, value: any) => Promise<void>

  // Keyboard navigation actions
  setFocusedCell: (cell: { row: number; col: number } | null) => void
  moveFocus: (direction: 'up' | 'down' | 'left' | 'right') => void
  moveFocusTab: (reverse?: boolean) => void

  // Bulk selection actions
  toggleRowSelection: (rowId: string) => void
  toggleAllRows: () => void
  selectRange: (fromIndex: number, toIndex: number) => void
  clearSelection: () => void
  bulkDelete: (rowIds: string[]) => Promise<void>
  bulkEdit: (rowIds: string[], column: string, value: any) => Promise<void>

  // Saved view actions
  loadViews: () => Promise<void>
  activateView: (viewId: string | null) => void
  saveView: (name: string) => Promise<void>
  renameView: (viewId: string, name: string) => Promise<void>
  deleteView: (viewId: string) => Promise<void>

  // Undo/redo actions
  undo: () => Promise<void>
  redo: () => Promise<void>
  clearUndoStack: () => void

  // CSV actions
  exportCsv: () => Promise<void>
  importCsv: (file: File, columnMapping: Record<string, string>) => Promise<ImportResult>

  // Relations
  loadRelations: (id: string) => Promise<RelationGroup[]>
}

// ---- Helpers --------------------------------------------------------------

function sessionHeaders(sessionId: string | null): Record<string, string> {
  if (!sessionId) return {}
  return { 'X-DB-Session-Id': sessionId }
}

function buildRowsQueryString(state: {
  page: number
  pageSize: number
  sortColumn: string | null
  sortDirection: 'asc' | 'desc' | null
  filters: FilterCondition[]
  searchTerm: string
}): string {
  const params = new URLSearchParams()
  params.set('page', String(state.page))
  params.set('page_size', String(state.pageSize))
  if (state.sortColumn) {
    params.set('sort_column', state.sortColumn)
    params.set('sort_direction', state.sortDirection || 'asc')
  }
  if (state.filters.length > 0) {
    params.set('filters', JSON.stringify(state.filters))
  }
  if (state.searchTerm) {
    params.set('search', state.searchTerm)
  }
  return params.toString()
}

// ---- Store ----------------------------------------------------------------

export const useDbBrowserStore = create<DbBrowserState>((set, get) => ({
  // Initial state
  schemas: [],
  schemasLoading: false,
  activeSchema: null,
  activeTable: null,
  columns: [],
  rows: [],
  totalRows: 0,
  filteredRows: 0,
  page: 1,
  pageSize: 50,
  sortColumn: null,
  sortDirection: null,
  filters: [],
  searchTerm: '',
  rowsLoading: false,
  activeRow: null,
  dirtyFields: new Set(),
  layouts: {},
  fieldHints: {},
  editingCell: null,
  focusedCell: null,
  selectedRows: new Set(),
  lastSelectedRowIndex: null,
  views: [],
  activeViewId: null,
  undoStack: [],
  redoStack: [],
  sessionId: null,

  // ---------- Core actions --------------------------------------------------

  loadSchemas: async () => {
    set({ schemasLoading: true })
    try {
      const res = await api.get('/api/db/schemas')
      const schemas = parseLoose(z.array(SchemaInfoSchema), res.data, 'GET /api/db/schemas')
      set({ schemas, schemasLoading: false })
    } catch {
      set({ schemasLoading: false })
    }
  },

  selectTable: async (schema, table) => {
    set({
      activeSchema: schema,
      activeTable: table,
      page: 1,
      sortColumn: null,
      sortDirection: null,
      filters: [],
      searchTerm: '',
      selectedRows: new Set(),
      lastSelectedRowIndex: null,
      editingCell: null,
      focusedCell: null,
      activeRow: null,
      dirtyFields: new Set(),
      activeViewId: null,
    })

    // Load columns
    try {
      const res = await api.get(`/api/db/${schema}/${table}/columns`)
      const columns = parseLoose(z.array(ColumnMetaSchema), res.data, `GET /api/db/${schema}/${table}/columns`)
      set({ columns })
    } catch {
      set({ columns: [] })
    }

    // Load rows
    await get().loadRows()

    // Load layout config for this table
    await get().loadLayout(schema, table)

    // Load views for this table
    await get().loadViews()
  },

  loadRows: async () => {
    const { activeSchema, activeTable } = get()
    if (!activeSchema || !activeTable) return

    set({ rowsLoading: true })
    try {
      const qs = buildRowsQueryString(get())
      const res = await api.get(`/api/db/${activeSchema}/${activeTable}/rows?${qs}`)
      const data = parseLoose(RowsResponseSchema, res.data, `GET /api/db/${activeSchema}/${activeTable}/rows`)
      set({
        rows: data.rows,
        totalRows: data.total_rows,
        filteredRows: data.filtered_rows,
        rowsLoading: false,
      })
    } catch {
      set({ rows: [], totalRows: 0, filteredRows: 0, rowsLoading: false })
    }
  },

  setPage: (page) => {
    set({ page })
    get().loadRows()
  },

  setPageSize: (size) => {
    set({ pageSize: size, page: 1 })
    get().loadRows()
  },

  setSort: (column) => {
    const { sortColumn, sortDirection } = get()
    if (sortColumn === column) {
      if (sortDirection === 'asc') {
        set({ sortDirection: 'desc' })
      } else if (sortDirection === 'desc') {
        // Third click clears sort
        set({ sortColumn: null, sortDirection: null })
      } else {
        set({ sortDirection: 'asc' })
      }
    } else {
      set({ sortColumn: column, sortDirection: 'asc' })
    }
    set({ page: 1 })
    get().loadRows()
  },

  setFilters: (filters) => {
    set({ filters, page: 1 })
    get().loadRows()
  },

  setSearch: (term) => {
    set({ searchTerm: term, page: 1 })
    get().loadRows()
  },

  // ---------- Detail actions ------------------------------------------------

  loadRow: async (id) => {
    const { activeSchema, activeTable } = get()
    if (!activeSchema || !activeTable) return

    try {
      const res = await api.get(`/api/db/${activeSchema}/${activeTable}/rows/${id}`)
      const data = parseLoose(z.record(z.string(), z.any()), res.data, `GET /api/db/${activeSchema}/${activeTable}/rows/${id}`)
      set({ activeRow: data, dirtyFields: new Set() })
    } catch {
      set({ activeRow: null })
    }
  },

  saveRow: async (updates) => {
    const { activeSchema, activeTable, activeRow, sessionId } = get()
    if (!activeSchema || !activeTable || !activeRow) return

    const pkCol = get().columns.find(c => c.is_pk)
    if (!pkCol) return
    const rowId = activeRow[pkCol.column_name]

    const headers = sessionHeaders(sessionId)
    const res = await api.patch(
      `/api/db/${activeSchema}/${activeTable}/rows/${rowId}`,
      updates,
      headers
    )
    const data = parseLoose(z.record(z.string(), z.any()), res.data, `PATCH /api/db/${activeSchema}/${activeTable}/rows/${rowId}`)
    set({ activeRow: data, dirtyFields: new Set() })
  },

  createRow: async (values) => {
    const { activeSchema, activeTable, sessionId } = get()
    if (!activeSchema || !activeTable) return null

    const headers = sessionHeaders(sessionId)
    const res = await api.post(
      `/api/db/${activeSchema}/${activeTable}/rows`,
      values,
      headers
    )
    const data = parseLoose(z.record(z.string(), z.any()), res.data, `POST /api/db/${activeSchema}/${activeTable}/rows`)
    // Refresh the rows list
    await get().loadRows()
    return data
  },

  deleteRow: async (id) => {
    const { activeSchema, activeTable, sessionId } = get()
    if (!activeSchema || !activeTable) return

    const headers = sessionHeaders(sessionId)
    await api.delete(`/api/db/${activeSchema}/${activeTable}/rows/${id}`, headers)
    set({ activeRow: null })
    await get().loadRows()
  },

  // ---------- Field hints ---------------------------------------------------

  loadFieldHints: async () => {
    try {
      const res = await api.get('/api/db/field-hints')
      const data = parseLoose(z.array(FieldHintSchema), res.data, 'GET /api/db/field-hints')
      const hints: Record<string, FieldHint> = {}
      for (const h of data) {
        hints[h.column_name] = h
      }
      set({ fieldHints: hints })
    } catch {
      // Non-fatal — field hints enhance UX but aren't required
    }
  },

  // ---------- Layout --------------------------------------------------------

  saveLayout: async (schema, table, config) => {
    // Backend expects { list_config, detail_config } shape
    await api.put(`/api/db/layouts/${schema}/${table}`, {
      list_config: config.list || {},
      detail_config: config.detail || {},
    })
    const key = `${schema}.${table}`
    set(state => ({
      layouts: { ...state.layouts, [key]: config },
    }))
  },

  loadLayout: async (schema, table) => {
    try {
      const res = await api.get(`/api/db/layouts/${schema}/${table}`)
      const key = `${schema}.${table}`
      const config: LayoutConfig = {
        list: res.data.list_config || {},
        detail: res.data.detail_config || {},
      }
      set(state => ({
        layouts: { ...state.layouts, [key]: config },
      }))
    } catch {
      // Non-fatal — layout will use defaults
    }
  },

  // ---------- Inline editing actions ----------------------------------------

  startEditing: (row, col) => {
    set({ editingCell: { row, col } })
  },

  stopEditing: () => {
    set({ editingCell: null })
  },

  saveCellValue: async (rowId, column, value) => {
    const { activeSchema, activeTable, sessionId } = get()
    if (!activeSchema || !activeTable) return

    const headers = sessionHeaders(sessionId)
    try {
      await api.patch(
        `/api/db/${activeSchema}/${activeTable}/rows/${rowId}`,
        { [column]: value },
        headers
      )
      // Refresh the affected row in the rows list
      set(state => ({
        rows: state.rows.map(r => {
          const pkCol = state.columns.find(c => c.is_pk)
          if (pkCol && String(r[pkCol.column_name]) === String(rowId)) {
            return { ...r, [column]: value }
          }
          return r
        }),
        editingCell: null,
      }))
    } catch (err: any) {
      // Revert — caller should handle toast notification
      set({ editingCell: null })
      throw err
    }
  },

  // ---------- Keyboard navigation actions -----------------------------------

  setFocusedCell: (cell) => {
    set({ focusedCell: cell })
  },

  moveFocus: (direction) => {
    const { focusedCell, rows, columns } = get()
    if (!focusedCell) return

    const editableCols = columns.filter(c => !c.is_pk)
    const maxRow = rows.length - 1
    const maxCol = editableCols.length - 1

    let { row, col } = focusedCell
    switch (direction) {
      case 'up': row = Math.max(0, row - 1); break
      case 'down': row = Math.min(maxRow, row + 1); break
      case 'left': col = Math.max(0, col - 1); break
      case 'right': col = Math.min(maxCol, col + 1); break
    }
    set({ focusedCell: { row, col } })
  },

  moveFocusTab: (reverse = false) => {
    const { focusedCell, rows, columns } = get()
    if (!focusedCell) return

    const editableCols = columns.filter(c => !c.is_pk)
    const maxRow = rows.length - 1
    const maxCol = editableCols.length - 1

    let { row, col } = focusedCell
    if (reverse) {
      col--
      if (col < 0) {
        col = maxCol
        row = Math.max(0, row - 1)
      }
    } else {
      col++
      if (col > maxCol) {
        col = 0
        row = Math.min(maxRow, row + 1)
      }
    }
    set({ focusedCell: { row, col } })
  },

  // ---------- Bulk selection actions ----------------------------------------

  toggleRowSelection: (rowId) => {
    set(state => {
      const next = new Set(state.selectedRows)
      if (next.has(rowId)) {
        next.delete(rowId)
      } else {
        next.add(rowId)
      }
      // Track last selected index for shift-click range
      const pkCol = state.columns.find(c => c.is_pk)
      const idx = pkCol
        ? state.rows.findIndex(r => String(r[pkCol.column_name]) === rowId)
        : null
      return { selectedRows: next, lastSelectedRowIndex: idx }
    })
  },

  toggleAllRows: () => {
    set(state => {
      const pkCol = state.columns.find(c => c.is_pk)
      if (!pkCol) return state

      const allIds = state.rows.map(r => String(r[pkCol.column_name]))
      const allSelected = allIds.every(id => state.selectedRows.has(id))

      if (allSelected) {
        return { selectedRows: new Set(), lastSelectedRowIndex: null }
      } else {
        return { selectedRows: new Set(allIds), lastSelectedRowIndex: null }
      }
    })
  },

  selectRange: (fromIndex, toIndex) => {
    set(state => {
      const pkCol = state.columns.find(c => c.is_pk)
      if (!pkCol) return state

      const start = Math.min(fromIndex, toIndex)
      const end = Math.max(fromIndex, toIndex)
      const next = new Set(state.selectedRows)
      for (let i = start; i <= end; i++) {
        const row = state.rows[i]
        if (row) next.add(String(row[pkCol.column_name]))
      }
      return { selectedRows: next, lastSelectedRowIndex: toIndex }
    })
  },

  clearSelection: () => {
    set({ selectedRows: new Set(), lastSelectedRowIndex: null })
  },

  bulkDelete: async (rowIds) => {
    const { activeSchema, activeTable, sessionId } = get()
    if (!activeSchema || !activeTable) return

    const headers = sessionHeaders(sessionId)
    await api.post(`/api/db/${activeSchema}/${activeTable}/bulk-delete`, { ids: rowIds }, headers)
    set({ selectedRows: new Set(), lastSelectedRowIndex: null })
    await get().loadRows()
  },

  bulkEdit: async (rowIds, column, value) => {
    const { activeSchema, activeTable, sessionId } = get()
    if (!activeSchema || !activeTable) return

    const headers = sessionHeaders(sessionId)
    await api.post(`/api/db/${activeSchema}/${activeTable}/bulk-edit`, {
      ids: rowIds,
      column,
      value,
    }, headers)
    await get().loadRows()
  },

  // ---------- Saved view actions --------------------------------------------

  loadViews: async () => {
    const { activeSchema, activeTable } = get()
    if (!activeSchema || !activeTable) return

    try {
      const res = await api.get(`/api/db/views/${activeSchema}/${activeTable}`)
      const views = parseLoose(z.array(SavedViewSchema), res.data, `GET /api/db/views/${activeSchema}/${activeTable}`)
      set({ views })
    } catch {
      set({ views: [] })
    }
  },

  activateView: (viewId) => {
    if (!viewId) {
      // "All" view — clear filters/sort
      set({
        activeViewId: null,
        filters: [],
        sortColumn: null,
        sortDirection: null,
        page: 1,
      })
      get().loadRows()
      return
    }

    const view = get().views.find(v => v.id === viewId)
    if (!view) return

    set({
      activeViewId: viewId,
      filters: view.config.filters || [],
      sortColumn: view.config.sortColumn || null,
      sortDirection: view.config.sortDirection || null,
      page: 1,
    })
    get().loadRows()
  },

  saveView: async (name) => {
    const { activeSchema, activeTable, filters, sortColumn, sortDirection } = get()
    if (!activeSchema || !activeTable) return

    const config = { filters, sortColumn, sortDirection, columns: [] }
    const res = await api.post(`/api/db/views/${activeSchema}/${activeTable}`, {
      name,
      config,
    })
    const view = parseLoose(SavedViewSchema, res.data, `POST /api/db/views/${activeSchema}/${activeTable}`)
    set(state => ({ views: [...state.views, view] }))
  },

  renameView: async (viewId, name) => {
    const { activeSchema, activeTable } = get()
    if (!activeSchema || !activeTable) return

    await api.patch(`/api/db/views/${activeSchema}/${activeTable}/${viewId}`, { name })
    set(state => ({
      views: state.views.map(v => v.id === viewId ? { ...v, name } : v),
    }))
  },

  deleteView: async (viewId) => {
    const { activeSchema, activeTable, activeViewId } = get()
    if (!activeSchema || !activeTable) return

    await api.delete(`/api/db/views/${activeSchema}/${activeTable}/${viewId}`)
    set(state => ({
      views: state.views.filter(v => v.id !== viewId),
      activeViewId: activeViewId === viewId ? null : activeViewId,
    }))
  },

  // ---------- Undo/redo actions ---------------------------------------------

  undo: async () => {
    const { sessionId } = get()
    if (!sessionId) return

    const headers = sessionHeaders(sessionId)
    try {
      const res = await api.post('/api/db/undo', undefined, headers)
      if (res.data) {
        const entry = parseLoose(UndoEntrySchema, res.data, 'POST /api/db/undo')
        set(state => ({
          undoStack: state.undoStack.slice(0, -1),
          redoStack: [...state.redoStack, entry],
        }))
      }
      await get().loadRows()
    } catch {
      // Undo failed — no entries to undo
    }
  },

  redo: async () => {
    const { sessionId } = get()
    if (!sessionId) return

    const headers = sessionHeaders(sessionId)
    try {
      const res = await api.post('/api/db/redo', undefined, headers)
      if (res.data) {
        const entry = parseLoose(UndoEntrySchema, res.data, 'POST /api/db/redo')
        set(state => ({
          redoStack: state.redoStack.slice(0, -1),
          undoStack: [...state.undoStack, entry],
        }))
      }
      await get().loadRows()
    } catch {
      // Redo failed — no entries to redo
    }
  },

  clearUndoStack: () => {
    set({ undoStack: [], redoStack: [] })
  },

  // ---------- CSV actions ---------------------------------------------------

  exportCsv: async () => {
    const { activeSchema, activeTable } = get()
    if (!activeSchema || !activeTable) return

    const qs = buildRowsQueryString(get())
    // Use raw fetch for file download (api client expects JSON)
    const token = (await import('../stores/auth')).useAuthStore.getState().accessToken
    const res = await fetch(`/api/db/${activeSchema}/${activeTable}/export-csv?${qs}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${activeSchema}_${activeTable}.csv`
    a.click()
    URL.revokeObjectURL(url)
  },

  importCsv: async (file, columnMapping) => {
    const { activeSchema, activeTable } = get()
    if (!activeSchema || !activeTable) {
      return { total_rows: 0, imported_rows: 0, failed_rows: [] }
    }

    // Use FormData for multipart upload
    const token = (await import('../stores/auth')).useAuthStore.getState().accessToken
    const formData = new FormData()
    formData.append('file', file)
    formData.append('column_mapping', JSON.stringify(columnMapping))

    const res = await fetch(`/api/db/${activeSchema}/${activeTable}/import-csv`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    })

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: 'Import failed' }))
      throw { response: { status: res.status, data: err } }
    }

    const result: ImportResult = await res.json()
    const data = parseLoose(ImportResultSchema, result, 'POST /api/db/.../import-csv')
    await get().loadRows()
    return data
  },

  // ---------- Relations -----------------------------------------------------

  loadRelations: async (id) => {
    const { activeSchema, activeTable } = get()
    if (!activeSchema || !activeTable) return []

    try {
      const res = await api.get(`/api/db/${activeSchema}/${activeTable}/${id}/relations`)
      const data = parseLoose(z.array(RelationGroupSchema), res.data, `GET /api/db/.../${id}/relations`)
      return data
    } catch {
      return []
    }
  },
}))
