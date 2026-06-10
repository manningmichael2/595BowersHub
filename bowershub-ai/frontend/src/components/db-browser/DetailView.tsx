/**
 * DetailView — single-row editing form for the DB Browser.
 *
 * Displays all columns for a row in a responsive form layout using react-grid-layout
 * (same library as the dashboard). Fields can be dragged and resized when layout
 * edit mode is active. Read-only fields (PK, created_at, updated_at, archived_at)
 * are visually distinguished. Tracks dirty fields and only PATCHes modified values on save.
 * Supports prev/next row navigation respecting current filters/sort.
 *
 * _Requirements: 7.1, 7.4, 7.5_
 */

import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Responsive, WidthProvider } from 'react-grid-layout/legacy'
import type { Layout, LayoutItem } from 'react-grid-layout/legacy'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { useDbBrowserStore, ColumnMeta } from '../../stores/db-browser'
import { useIsAdmin } from '../../hooks/useIsAdmin'
import ImageGallery from './ImageGallery'
import LayoutSettings from './LayoutSettings'
import CreateRowDialog from './CreateRowDialog'
import RelationSections from './RelationSections'
import SmartFieldRenderer from './SmartFieldRenderer'

const ResponsiveGridLayout = WidthProvider(Responsive)

// ---- Constants ------------------------------------------------------------

/** Columns that are always read-only regardless of type */
const READ_ONLY_SUFFIXES = ['created_at', 'updated_at', 'archived_at']

function isReadOnlyColumn(col: ColumnMeta): boolean {
  if (col.is_pk) return true
  return READ_ONLY_SUFFIXES.includes(col.column_name)
}

/** Grid breakpoints and columns config */
const GRID_BREAKPOINTS = { lg: 1024, md: 640, sm: 0 }
const GRID_COLS = { lg: 6, md: 4, sm: 1 }
const GRID_ROW_HEIGHT = 80
const GRID_MARGIN: [number, number] = [12, 12]

// ---- Component ------------------------------------------------------------

export default function DetailView() {
  const { schema, table, id } = useParams<{ schema: string; table: string; id: string }>()
  const navigate = useNavigate()
  const isAdmin = useIsAdmin()

  // Store state
  const activeRow = useDbBrowserStore(s => s.activeRow)
  const columns = useDbBrowserStore(s => s.columns)
  const rows = useDbBrowserStore(s => s.rows)
  const activeSchema = useDbBrowserStore(s => s.activeSchema)
  const activeTable = useDbBrowserStore(s => s.activeTable)
  const schemas = useDbBrowserStore(s => s.schemas)
  const layouts = useDbBrowserStore(s => s.layouts)
  const loadRow = useDbBrowserStore(s => s.loadRow)
  const saveRow = useDbBrowserStore(s => s.saveRow)
  const selectTable = useDbBrowserStore(s => s.selectTable)
  const saveLayout = useDbBrowserStore(s => s.saveLayout)

  // Local form state — tracks edits before save
  const [formValues, setFormValues] = useState<Record<string, any>>({})
  const [dirtyFields, setDirtyFields] = useState<Set<string>>(new Set())
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  // Duplicate dialog state
  const [showDuplicateDialog, setShowDuplicateDialog] = useState(false)
  const [duplicateInitialValues, setDuplicateInitialValues] = useState<Record<string, any> | undefined>(undefined)

  // Layout edit mode state
  const [layoutEditMode, setLayoutEditMode] = useState(false)

  // Derive the layout key and current layout
  const layoutKey = activeSchema && activeTable ? `${activeSchema}.${activeTable}` : null
  const currentLayout = layoutKey ? layouts[layoutKey] : null

  // Ordered columns based on layout settings (visibility filtering)
  const orderedColumns = useMemo(() => {
    if (!columns.length) return []
    if (currentLayout?.detail?.fields?.length) {
      const savedFields = currentLayout.detail.fields
      const savedMap = new Map(savedFields.map(f => [f.name, f]))
      const ordered: { col: ColumnMeta; config: { visible: boolean; width: 25 | 33 | 50 | 100; height: 'small' | 'medium' | 'large' } }[] = []

      // Add saved fields in order
      for (const sf of savedFields) {
        const col = columns.find(c => c.column_name === sf.name)
        if (col && sf.visible) {
          ordered.push({ col, config: { visible: sf.visible, width: sf.width, height: sf.height } })
        }
      }

      // Add any new columns not in saved layout
      for (const col of columns) {
        if (!savedMap.has(col.column_name)) {
          ordered.push({ col, config: { visible: true, width: 50, height: 'small' } })
        }
      }

      return ordered
    }

    // Default: all visible, 50% width
    return columns.map(col => ({ col, config: { visible: true, width: 50 as const, height: 'small' as const } }))
  }, [columns, currentLayout])

  // Build react-grid-layout items from orderedColumns + saved layout
  const gridLayout = useMemo((): LayoutItem[] => {
    return orderedColumns.map((item, index) => {
      const key = item.col.column_name
      const savedFields = currentLayout?.detail?.fields
      const savedField = savedFields?.find(f => f.name === key)

      // If there's a saved grid position (x, y, w, h stored in the field config)
      // we'll use the width to infer w, and position to infer placement
      if (savedField && (savedField as any).gridX !== undefined) {
        const gf = savedField as any
        return {
          i: key,
          x: gf.gridX ?? 0,
          y: gf.gridY ?? index,
          w: gf.gridW ?? 2,
          h: gf.gridH ?? 1,
          minW: 1,
          minH: 1,
        }
      }

      // Auto-place: 3 columns on desktop (each field w=2 in a 6-col grid = 33%)
      const widthToW = (w: number): number => {
        if (w === 100) return 6
        if (w === 50) return 3
        if (w === 33) return 2
        if (w === 25) return 1
        return 2
      }

      const w = widthToW(item.config.width)
      const col = (index * 2) % 6
      const row = Math.floor((index * 2) / 6)

      return {
        i: key,
        x: col,
        y: row,
        w,
        h: 1,
        minW: 1,
        minH: 1,
      }
    })
  }, [orderedColumns, currentLayout])

  // Handle layout change from react-grid-layout
  const handleLayoutChange = useCallback((newLayout: LayoutItem[]) => {
    if (!layoutEditMode || !activeSchema || !activeTable) return

    const existing = layoutKey ? layouts[layoutKey] : null

    // Build updated fields array preserving visibility and mapping grid positions
    const updatedFields = newLayout.map((layoutItem, idx) => {
      const existingField = currentLayout?.detail?.fields?.find(f => f.name === layoutItem.i)
      const col = orderedColumns.find(item => item.col.column_name === layoutItem.i)

      // Map grid width back to percentage for compatibility
      const wToWidth = (w: number): 25 | 33 | 50 | 100 => {
        if (w >= 6) return 100
        if (w >= 4) return 50
        if (w >= 3) return 50
        if (w >= 2) return 33
        return 25
      }

      return {
        name: layoutItem.i,
        visible: existingField?.visible ?? true,
        position: idx,
        width: wToWidth(layoutItem.w),
        height: (existingField?.height ?? col?.config.height ?? 'small') as 'small' | 'medium' | 'large',
        // Store grid positions for exact restoration
        gridX: layoutItem.x,
        gridY: layoutItem.y,
        gridW: layoutItem.w,
        gridH: layoutItem.h,
      }
    })

    // Also include hidden fields at the end
    if (currentLayout?.detail?.fields) {
      for (const sf of currentLayout.detail.fields) {
        if (!sf.visible && !updatedFields.find(f => f.name === sf.name)) {
          updatedFields.push({ ...sf, position: updatedFields.length, gridX: 0, gridY: updatedFields.length, gridW: 2, gridH: 1 } as any)
        }
      }
    }

    saveLayout(activeSchema, activeTable, {
      list: existing?.list ?? { columns: [] },
      detail: { fields: updatedFields as any },
    })
  }, [layoutEditMode, activeSchema, activeTable, layoutKey, layouts, currentLayout, orderedColumns, saveLayout])

  // Ensure the table is selected (handles direct navigation to /db/:schema/:table/:id)
  useEffect(() => {
    if (schema && table && (schema !== activeSchema || table !== activeTable)) {
      selectTable(schema, table)
    }
  }, [schema, table, activeSchema, activeTable, selectTable])

  // Load the specific row
  useEffect(() => {
    if (id && schema && table) {
      loadRow(id)
    }
  }, [id, schema, table, loadRow])

  // Sync form values when activeRow changes (fresh load or after save)
  useEffect(() => {
    if (activeRow) {
      setFormValues({ ...activeRow })
      setDirtyFields(new Set())
      setSaveError(null)
    }
  }, [activeRow])

  // Derive PK column
  const pkColumn = useMemo(
    () => columns.find(c => c.is_pk),
    [columns]
  )

  // Check if this table has image support (link table)
  const hasImageSupport = useMemo(() => {
    if (!activeSchema || !activeTable) return false
    const schemaInfo = schemas.find(s => s.name === activeSchema)
    if (!schemaInfo) return false
    const tableInfo = schemaInfo.tables.find(t => t.name === activeTable)
    return tableInfo?.has_link_table ?? false
  }, [schemas, activeSchema, activeTable])

  // Determine adjacent rows for prev/next navigation
  const { prevId, nextId } = useMemo(() => {
    if (!pkColumn || !rows.length || !id) return { prevId: null, nextId: null }

    const currentIndex = rows.findIndex(
      r => String(r[pkColumn.column_name]) === String(id)
    )

    if (currentIndex === -1) return { prevId: null, nextId: null }

    const prev = currentIndex > 0
      ? String(rows[currentIndex - 1][pkColumn.column_name])
      : null
    const next = currentIndex < rows.length - 1
      ? String(rows[currentIndex + 1][pkColumn.column_name])
      : null

    return { prevId: prev, nextId: next }
  }, [pkColumn, rows, id])

  // Row title — use PK value or generic label
  const rowTitle = useMemo(() => {
    if (!pkColumn || !activeRow) return `Row #${id}`
    const pkValue = activeRow[pkColumn.column_name]
    // Try to find a "name" or "title" column for a better label
    const nameCol = columns.find(c =>
      ['name', 'title', 'label', 'description'].includes(c.column_name) &&
      !c.is_pk
    )
    if (nameCol && activeRow[nameCol.column_name]) {
      return String(activeRow[nameCol.column_name])
    }
    return `${pkColumn.column_name}: ${pkValue}`
  }, [pkColumn, activeRow, columns, id])

  // Handle field value change
  const handleFieldChange = useCallback((columnName: string, value: any) => {
    setFormValues(prev => ({ ...prev, [columnName]: value }))
    setDirtyFields(prev => {
      const next = new Set(prev)
      // Check if value differs from original
      const originalValue = activeRow ? activeRow[columnName] : undefined
      if (value === originalValue || (value === '' && originalValue === null)) {
        next.delete(columnName)
      } else {
        next.add(columnName)
      }
      return next
    })
    setSaveError(null)
  }, [activeRow])

  // Save only dirty fields
  const handleSave = useCallback(async () => {
    if (dirtyFields.size === 0) return

    const updates: Record<string, any> = {}
    dirtyFields.forEach(field => {
      const value = formValues[field]
      // Convert empty strings to null for nullable fields
      const col = columns.find(c => c.column_name === field)
      if (col && col.is_nullable === 'YES' && value === '') {
        updates[field] = null
      } else {
        updates[field] = value
      }
    })

    setSaving(true)
    setSaveError(null)
    try {
      await saveRow(updates)
      setDirtyFields(new Set())
    } catch (err: any) {
      const message = err?.response?.data?.detail || err?.message || 'Save failed'
      setSaveError(message)
    } finally {
      setSaving(false)
    }
  }, [dirtyFields, formValues, columns, saveRow])

  // Navigation handlers
  const handleBack = useCallback(() => {
    navigate(`/db/${schema}/${table}`)
  }, [navigate, schema, table])

  // Duplicate handler — copies all fields except PK and timestamps
  const handleDuplicate = useCallback(() => {
    if (!activeRow || !columns.length) return

    const valuesToCopy: Record<string, any> = {}
    columns.forEach(col => {
      if (col.is_pk) return
      if (READ_ONLY_SUFFIXES.includes(col.column_name)) return
      valuesToCopy[col.column_name] = activeRow[col.column_name]
    })

    setDuplicateInitialValues(valuesToCopy)
    setShowDuplicateDialog(true)
  }, [activeRow, columns])

  const handlePrev = useCallback(() => {
    if (prevId) navigate(`/db/${schema}/${table}/${prevId}`)
  }, [navigate, schema, table, prevId])

  const handleNext = useCallback(() => {
    if (nextId) navigate(`/db/${schema}/${table}/${nextId}`)
  }, [navigate, schema, table, nextId])

  // ---- Swipe gesture handling for row navigation on touch devices (Req 23.5) ----
  const touchStartRef = useRef<{ x: number; y: number; time: number } | null>(null)
  const formContainerRef = useRef<HTMLDivElement>(null)

  const handleTouchStart = useCallback((e: React.TouchEvent) => {
    const touch = e.touches[0]
    touchStartRef.current = { x: touch.clientX, y: touch.clientY, time: Date.now() }
  }, [])

  const handleTouchEnd = useCallback((e: React.TouchEvent) => {
    if (!touchStartRef.current) return

    const touch = e.changedTouches[0]
    const deltaX = touch.clientX - touchStartRef.current.x
    const deltaY = touch.clientY - touchStartRef.current.y
    const elapsed = Date.now() - touchStartRef.current.time

    // Require: horizontal distance > 80px, mostly horizontal (not vertical scroll),
    // and gesture completed within 500ms
    const MIN_SWIPE_DISTANCE = 80
    const isHorizontal = Math.abs(deltaX) > Math.abs(deltaY) * 1.5
    const isFastEnough = elapsed < 500

    if (isHorizontal && isFastEnough && Math.abs(deltaX) > MIN_SWIPE_DISTANCE) {
      if (deltaX > 0 && prevId) {
        navigate(`/db/${schema}/${table}/${prevId}`)
      } else if (deltaX < 0 && nextId) {
        navigate(`/db/${schema}/${table}/${nextId}`)
      }
    }

    touchStartRef.current = null
  }, [navigate, schema, table, prevId, nextId])

  // Loading state
  if (!activeRow) {
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
          <p className="text-sm">Loading row…</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* Header with title, navigation, and back button */}
      <div
        className="shrink-0 px-4 py-3 flex items-center justify-between gap-3 border-b"
        style={{
          borderColor: 'var(--color-border)',
          backgroundColor: 'var(--color-surface)',
        }}
      >
        <div className="flex items-center gap-3 min-w-0">
          {/* Back button — touch-friendly (Req 23.4) */}
          <button
            type="button"
            onClick={handleBack}
            className="shrink-0 p-2.5 sm:p-1.5 rounded transition-colors hover:opacity-80 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Back to table"
            title="Back to table"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="15 18 9 12 15 6" />
            </svg>
          </button>

          {/* Row title */}
          <h2
            className="text-sm font-semibold truncate"
            style={{ color: 'var(--color-text)' }}
            title={rowTitle}
          >
            {rowTitle}
          </h2>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Prev/Next navigation — touch-friendly (Req 23.4) */}
          <button
            type="button"
            onClick={handlePrev}
            disabled={!prevId}
            className="text-xs px-2 py-1 rounded disabled:opacity-30 transition-opacity min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
            aria-label="Previous row"
            title="Previous row"
          >
            ← <span className="hidden sm:inline">Prev</span>
          </button>
          <button
            type="button"
            onClick={handleNext}
            disabled={!nextId}
            className="text-xs px-2 py-1 rounded disabled:opacity-30 transition-opacity min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
            aria-label="Next row"
            title="Next row"
          >
            <span className="hidden sm:inline">Next</span> →
          </button>

          {/* Duplicate button — touch-friendly (Req 23.4), hidden for non-admin (Req 21.3) */}
          {isAdmin && (
          <button
            type="button"
            onClick={handleDuplicate}
            className="text-xs px-2.5 py-1.5 rounded font-medium transition-opacity hover:opacity-80 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{
              backgroundColor: 'transparent',
              color: 'var(--color-text)',
              border: '1px solid var(--color-border)',
            }}
            aria-label="Duplicate row"
            title="Duplicate row"
          >
            <span className="sm:hidden">⧉</span>
            <span className="hidden sm:inline">⧉ Duplicate</span>
          </button>
          )}

          {/* Layout edit mode toggle */}
          {isAdmin && (
          <button
            type="button"
            onClick={() => setLayoutEditMode(prev => !prev)}
            className="text-xs px-2.5 py-1.5 rounded font-medium transition-colors min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{
              backgroundColor: layoutEditMode ? 'var(--color-primary)' : 'transparent',
              color: layoutEditMode ? 'var(--color-on-primary, #fff)' : 'var(--color-text-muted)',
              border: layoutEditMode ? 'none' : '1px solid var(--color-border)',
            }}
            aria-label={layoutEditMode ? 'Done editing layout' : 'Edit layout'}
            title={layoutEditMode ? 'Done editing layout' : 'Edit layout (drag & resize fields)'}
          >
            {layoutEditMode ? 'Done' : '⠿'}
          </button>
          )}

          {/* Layout settings gear icon */}
          <LayoutSettings />

          {/* Save button — touch-friendly (Req 23.4), hidden for non-admin (Req 21.3) */}
          {isAdmin && (
          <button
            type="button"
            onClick={handleSave}
            disabled={dirtyFields.size === 0 || saving}
            className="text-xs px-3 py-1.5 rounded font-medium transition-opacity disabled:opacity-40 min-w-[44px] min-h-[44px] sm:min-w-0 sm:min-h-0 flex items-center justify-center"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
            }}
          >
            {saving ? 'Saving…' : `Save${dirtyFields.size > 0 ? ` (${dirtyFields.size})` : ''}`}
          </button>
          )}
        </div>
      </div>

      {/* Error banner */}
      {saveError && (
        <div
          className="shrink-0 px-4 py-2 text-xs"
          style={{
            backgroundColor: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
            color: 'var(--color-error)',
            borderBottom: '1px solid color-mix(in srgb, var(--color-error) 20%, transparent)',
          }}
        >
          ⚠ {saveError}
        </div>
      )}

      {/* Form area — scrollable, with swipe gesture support on touch (Req 23.5) */}
      <div
        ref={formContainerRef}
        className="flex-1 min-h-0 overflow-y-auto px-4 py-4"
        onTouchStart={handleTouchStart}
        onTouchEnd={handleTouchEnd}
      >
        <div className="w-full">
          <ResponsiveGridLayout
            layouts={{
              lg: gridLayout,
              md: gridLayout.map(l => ({ ...l, w: Math.min(l.w, 4), x: l.x % 4 })),
              sm: gridLayout.map(l => ({ ...l, x: 0, w: 1 })),
            }}
            breakpoints={GRID_BREAKPOINTS}
            cols={GRID_COLS}
            rowHeight={GRID_ROW_HEIGHT}
            isDraggable={layoutEditMode}
            isResizable={layoutEditMode}
            onLayoutChange={(layout) => handleLayoutChange(layout as unknown as LayoutItem[])}
            margin={GRID_MARGIN}
            containerPadding={[0, 0] as [number, number]}
          >
            {orderedColumns.map((item) => {
              const col = item.col
              const readOnly = !isAdmin || isReadOnlyColumn(col)
              const value = formValues[col.column_name]
              const isDirty = dirtyFields.has(col.column_name)

              return (
                <div
                  key={col.column_name}
                  className={layoutEditMode ? 'ring-1 ring-[var(--color-primary)] rounded-lg' : ''}
                  style={{ overflow: 'hidden' }}
                >
                  <div className="h-full w-full p-1">
                    <FieldRow
                      column={col}
                      value={value}
                      readOnly={readOnly}
                      isDirty={isDirty}
                      onChange={(val) => handleFieldChange(col.column_name, val)}
                      schema={schema}
                      table={table}
                    />
                  </div>
                </div>
              )
            })}
          </ResponsiveGridLayout>
        </div>

        {/* Image gallery — shown when table has a link table */}
        {hasImageSupport && schema && table && id && (
          <div className="mt-6 max-w-4xl">
            <ImageGallery schema={schema} table={table} rowId={id} />
          </div>
        )}

        {/* Relation sections — shows related records from referencing tables */}
        {schema && table && id && (
          <RelationSections schema={schema} table={table} rowId={id} />
        )}
      </div>

      {/* Duplicate row dialog */}
      <CreateRowDialog
        open={showDuplicateDialog}
        onClose={() => setShowDuplicateDialog(false)}
        schema={schema || ''}
        table={table || ''}
        initialValues={duplicateInitialValues}
      />
    </div>
  )
}

// ---- FieldRow sub-component -----------------------------------------------

interface FieldRowProps {
  column: ColumnMeta
  value: any
  readOnly: boolean
  isDirty: boolean
  onChange: (value: any) => void
  schema?: string
  table?: string
}

/**
 * Renders a single field in the detail form using SmartFieldRenderer.
 * Read-only fields get a subtle background distinction and disabled inputs.
 * SmartFieldRenderer handles fraction, lookup, select, and other hint-based rendering.
 */
function FieldRow({ column, value, readOnly, isDirty, onChange, schema, table }: FieldRowProps) {
  return (
    <div
      className="flex flex-col gap-1 h-full"
      style={{
        borderLeft: isDirty ? '2px solid var(--color-primary)' : '2px solid transparent',
        paddingLeft: '0.5rem',
      }}
    >
      {/* Label */}
      <label
        className="text-xs font-medium flex items-center gap-1.5"
        style={{ color: 'var(--color-text-muted)' }}
        htmlFor={`field-${column.column_name}`}
      >
        {column.column_name}
        {column.is_pk && (
          <span
            className="text-[10px] px-1 py-0.5 rounded"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
            }}
          >
            PK
          </span>
        )}
        {readOnly && !column.is_pk && (
          <span
            className="text-[10px] px-1 py-0.5 rounded opacity-70"
            style={{
              backgroundColor: 'var(--color-border)',
              color: 'var(--color-text-muted)',
            }}
          >
            read-only
          </span>
        )}
        {isDirty && (
          <span
            className="w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: 'var(--color-primary)' }}
            title="Modified"
          />
        )}
      </label>

      {/* SmartFieldRenderer handles the input widget selection */}
      <SmartFieldRenderer
        column={column}
        value={value}
        onChange={onChange}
        hideLabel={true}
        readOnly={readOnly}
        schema={schema}
        table={table}
      />

      {/* Column type hint */}
      <span
        className="text-[10px]"
        style={{ color: 'var(--color-text-muted)', opacity: 0.6 }}
      >
        {column.data_type}
        {column.is_nullable === 'YES' ? ' • nullable' : ''}
      </span>
    </div>
  )
}

// ---- Helpers --------------------------------------------------------------
// (Field type resolution is handled by SmartFieldRenderer)
