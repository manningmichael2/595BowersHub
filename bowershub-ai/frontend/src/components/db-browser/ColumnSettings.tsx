/**
 * ColumnSettings — panel for configuring which columns are visible in
 * the table list view, and their display order.
 *
 * Features:
 * - Gear icon button that toggles the panel open/closed
 * - Column list with visibility toggle checkboxes
 * - Up/down arrows for reordering columns
 * - PK column is always shown (checkbox disabled, checked)
 * - Save button persists to the layout API via saveLayout
 * - Default behavior (no saved config): hide wide columns (notes, url,
 *   ai_summary, description), show everything else in DB order
 *
 * _Requirements: 11.1, 11.2, 11.3, 11.4_
 */
import { useState, useEffect, useMemo, useRef, useCallback } from 'react'
import { useDbBrowserStore, type LayoutConfig } from '../../stores/db-browser'

/** Column names that are hidden by default (wide/noisy columns). */
const DEFAULT_HIDDEN_COLUMNS = new Set([
  'notes',
  'url',
  'ai_summary',
  'description',
])

interface ColumnEntry {
  name: string
  visible: boolean
  position: number
}

export default function ColumnSettings() {
  const [isOpen, setIsOpen] = useState(false)
  const [columnEntries, setColumnEntries] = useState<ColumnEntry[]>([])
  const [saving, setSaving] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)

  // Store state
  const columns = useDbBrowserStore(s => s.columns)
  const activeSchema = useDbBrowserStore(s => s.activeSchema)
  const activeTable = useDbBrowserStore(s => s.activeTable)
  const layouts = useDbBrowserStore(s => s.layouts)
  const saveLayout = useDbBrowserStore(s => s.saveLayout)

  const layoutKey = activeSchema && activeTable ? `${activeSchema}.${activeTable}` : null
  const currentLayout = layoutKey ? layouts[layoutKey] : undefined

  // Derive PK column name
  const pkColumnName = useMemo(
    () => columns.find(c => c.is_pk)?.column_name ?? null,
    [columns]
  )

  // Build the column entries from layout config or defaults when table/columns change
  useEffect(() => {
    if (columns.length === 0) return

    const savedList = currentLayout?.list?.columns
    if (savedList && savedList.length > 0) {
      // Use saved config — ensure we include any new columns not yet in the saved config
      const savedMap = new Map(savedList.map(c => [c.name, c]))
      const entries: ColumnEntry[] = []
      let maxPos = savedList.reduce((m, c) => Math.max(m, c.position), 0)

      // First add all saved columns in position order
      const sorted = [...savedList].sort((a, b) => a.position - b.position)
      for (const s of sorted) {
        // Only include if column still exists
        if (columns.find(c => c.column_name === s.name)) {
          entries.push({ name: s.name, visible: s.visible, position: s.position })
        }
      }

      // Add any new columns not in saved config
      for (const col of columns) {
        if (!savedMap.has(col.column_name)) {
          maxPos++
          entries.push({
            name: col.column_name,
            visible: !DEFAULT_HIDDEN_COLUMNS.has(col.column_name),
            position: maxPos,
          })
        }
      }

      setColumnEntries(entries)
    } else {
      // Default: all columns in DB order, hide wide ones
      const entries: ColumnEntry[] = columns.map((col, idx) => ({
        name: col.column_name,
        visible: col.is_pk || !DEFAULT_HIDDEN_COLUMNS.has(col.column_name),
        position: idx,
      }))
      setColumnEntries(entries)
    }
  }, [columns, currentLayout])

  // Close panel when clicking outside
  useEffect(() => {
    if (!isOpen) return

    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen])

  // Toggle visibility (PK is always visible)
  const toggleVisibility = useCallback((name: string) => {
    setColumnEntries(prev =>
      prev.map(entry =>
        entry.name === name && name !== pkColumnName
          ? { ...entry, visible: !entry.visible }
          : entry
      )
    )
  }, [pkColumnName])

  // Move column up
  const moveUp = useCallback((index: number) => {
    if (index <= 0) return
    setColumnEntries(prev => {
      const next = [...prev]
      ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
      // Recalculate positions
      return next.map((entry, i) => ({ ...entry, position: i }))
    })
  }, [])

  // Move column down
  const moveDown = useCallback((index: number) => {
    setColumnEntries(prev => {
      if (index >= prev.length - 1) return prev
      const next = [...prev]
      ;[next[index], next[index + 1]] = [next[index + 1], next[index]]
      // Recalculate positions
      return next.map((entry, i) => ({ ...entry, position: i }))
    })
  }, [])

  // Save column config to the layout API
  const handleSave = useCallback(async () => {
    if (!activeSchema || !activeTable) return

    setSaving(true)
    try {
      // Get the existing detail config so we don't overwrite it
      const existingDetail = currentLayout?.detail ?? {}

      const config: LayoutConfig = {
        list: {
          columns: columnEntries.map((entry, i) => ({
            name: entry.name,
            visible: entry.visible,
            position: i,
          })),
        },
        detail: existingDetail as LayoutConfig['detail'],
      }

      await saveLayout(activeSchema, activeTable, config)
      setIsOpen(false)
    } catch (err) {
      console.error('Failed to save column settings', err)
    } finally {
      setSaving(false)
    }
  }, [activeSchema, activeTable, columnEntries, currentLayout, saveLayout])

  // Count visible columns for badge
  const visibleCount = columnEntries.filter(e => e.visible).length
  const totalCount = columnEntries.length

  return (
    <div className="relative" ref={panelRef}>
      {/* Gear icon toggle button */}
      <button
        type="button"
        onClick={() => setIsOpen(!isOpen)}
        className="text-xs px-2 py-1 rounded transition-opacity inline-flex items-center gap-1"
        style={{
          backgroundColor: isOpen ? 'var(--color-primary)' : 'var(--color-background)',
          color: isOpen ? 'var(--color-on-primary, #fff)' : 'var(--color-text-muted)',
          border: '1px solid var(--color-border)',
        }}
        title="Column settings"
        aria-label="Column settings"
        aria-expanded={isOpen}
      >
        <svg
          width="14"
          height="14"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
        <span className="hidden sm:inline">Columns</span>
      </button>

      {/* Dropdown panel */}
      {isOpen && (
        <div
          className="absolute right-0 top-full mt-1 z-50 rounded shadow-lg w-64 max-h-[70vh] flex flex-col"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          {/* Panel header */}
          <div
            className="px-3 py-2 border-b shrink-0"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <div className="flex items-center justify-between">
              <span
                className="text-xs font-semibold"
                style={{ color: 'var(--color-text)' }}
              >
                Columns ({visibleCount}/{totalCount})
              </span>
              <button
                type="button"
                onClick={() => setIsOpen(false)}
                className="text-xs opacity-60 hover:opacity-100"
                style={{ color: 'var(--color-text-muted)' }}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
          </div>

          {/* Column list */}
          <div className="flex-1 min-h-0 overflow-y-auto px-2 py-1">
            {columnEntries.map((entry, index) => {
              const isPk = entry.name === pkColumnName
              return (
                <div
                  key={entry.name}
                  className="flex items-center gap-1.5 px-1 py-1 rounded text-xs"
                  style={{ color: 'var(--color-text)' }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.backgroundColor =
                      'var(--color-row-hover, rgba(128,128,128,0.08))'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.backgroundColor = 'transparent'
                  }}
                >
                  {/* Visibility checkbox */}
                  <input
                    type="checkbox"
                    checked={entry.visible}
                    disabled={isPk}
                    onChange={() => toggleVisibility(entry.name)}
                    className="w-3.5 h-3.5 shrink-0 accent-[var(--color-primary)]"
                    title={isPk ? 'Primary key is always visible' : `Toggle ${entry.name}`}
                  />

                  {/* Column name */}
                  <span
                    className="flex-1 truncate"
                    style={{
                      opacity: entry.visible ? 1 : 0.5,
                      fontWeight: isPk ? 600 : 400,
                    }}
                  >
                    {entry.name}
                    {isPk && (
                      <span
                        className="ml-1 text-[10px]"
                        style={{ color: 'var(--color-text-muted)' }}
                      >
                        PK
                      </span>
                    )}
                  </span>

                  {/* Reorder buttons */}
                  <button
                    type="button"
                    onClick={() => moveUp(index)}
                    disabled={index === 0}
                    className="w-5 h-5 flex items-center justify-center rounded disabled:opacity-20 hover:opacity-80"
                    style={{ color: 'var(--color-text-muted)' }}
                    title="Move up"
                    aria-label={`Move ${entry.name} up`}
                  >
                    ▲
                  </button>
                  <button
                    type="button"
                    onClick={() => moveDown(index)}
                    disabled={index === columnEntries.length - 1}
                    className="w-5 h-5 flex items-center justify-center rounded disabled:opacity-20 hover:opacity-80"
                    style={{ color: 'var(--color-text-muted)' }}
                    title="Move down"
                    aria-label={`Move ${entry.name} down`}
                  >
                    ▼
                  </button>
                </div>
              )
            })}
          </div>

          {/* Save button */}
          <div
            className="px-3 py-2 border-t shrink-0"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="w-full text-xs py-1.5 rounded font-medium transition-opacity disabled:opacity-50"
              style={{
                backgroundColor: 'var(--color-primary)',
                color: 'var(--color-on-primary, #fff)',
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
