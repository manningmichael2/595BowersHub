/**
 * LayoutSettings — side panel for configuring detail view field layout.
 *
 * Shows all columns for the current table, allowing the user to:
 * - Reorder fields via ↑/↓ arrow buttons
 * - Toggle field visibility
 * - Set field width (25%, 33%, 50%, 100%)
 * - Set field height (small, medium, large)
 *
 * Defaults: all columns visible, 50% width, DB column order, small height.
 *
 * _Requirements: 10.1, 10.2, 10.3, 10.4, 10.6_
 */

import { useState, useCallback, useEffect } from 'react'
import { useDbBrowserStore, LayoutConfig } from '../../stores/db-browser'

// ---- Types ----------------------------------------------------------------

interface FieldConfig {
  name: string
  visible: boolean
  position: number
  width: 25 | 33 | 50 | 100
  height: 'small' | 'medium' | 'large'
}

// ---- Width / Height option arrays -----------------------------------------

const WIDTH_OPTIONS: { value: 25 | 33 | 50 | 100; label: string }[] = [
  { value: 25, label: '25%' },
  { value: 33, label: '33%' },
  { value: 50, label: '50%' },
  { value: 100, label: '100%' },
]

const HEIGHT_OPTIONS: { value: 'small' | 'medium' | 'large'; label: string }[] = [
  { value: 'small', label: 'S' },
  { value: 'medium', label: 'M' },
  { value: 'large', label: 'L' },
]

// ---- Component ------------------------------------------------------------

export default function LayoutSettings() {
  const columns = useDbBrowserStore(s => s.columns)
  const activeSchema = useDbBrowserStore(s => s.activeSchema)
  const activeTable = useDbBrowserStore(s => s.activeTable)
  const layouts = useDbBrowserStore(s => s.layouts)
  const saveLayout = useDbBrowserStore(s => s.saveLayout)

  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)

  // Derive the current layout key
  const layoutKey = activeSchema && activeTable ? `${activeSchema}.${activeTable}` : null

  // Build local field config from saved layout or defaults
  const [fields, setFields] = useState<FieldConfig[]>([])

  // Initialize fields from saved layout or create defaults
  useEffect(() => {
    if (!columns.length) return

    const saved = layoutKey ? layouts[layoutKey] : null

    if (saved?.detail?.fields?.length) {
      // Use saved layout — ensure all columns are represented
      const savedMap = new Map(saved.detail.fields.map(f => [f.name, f]))
      const merged: FieldConfig[] = []

      // First, add all saved fields in their saved order
      for (const sf of saved.detail.fields) {
        // Only include if column still exists
        if (columns.find(c => c.column_name === sf.name)) {
          merged.push({ ...sf })
        }
      }

      // Then add any new columns not in saved layout
      let maxPos = merged.length
      for (const col of columns) {
        if (!savedMap.has(col.column_name)) {
          merged.push({
            name: col.column_name,
            visible: true,
            position: maxPos++,
            width: 50,
            height: 'small',
          })
        }
      }

      setFields(merged)
    } else {
      // Default: all columns, 50% width, DB column order
      setFields(
        columns.map((col, i) => ({
          name: col.column_name,
          visible: true,
          position: i,
          width: 50,
          height: 'small',
        }))
      )
    }
  }, [columns, layoutKey, layouts])

  // Move a field up in the list
  const moveUp = useCallback((index: number) => {
    if (index <= 0) return
    setFields(prev => {
      const next = [...prev]
      ;[next[index - 1], next[index]] = [next[index], next[index - 1]]
      return next.map((f, i) => ({ ...f, position: i }))
    })
  }, [])

  // Move a field down in the list
  const moveDown = useCallback((index: number) => {
    setFields(prev => {
      if (index >= prev.length - 1) return prev
      const next = [...prev]
      ;[next[index], next[index + 1]] = [next[index + 1], next[index]]
      return next.map((f, i) => ({ ...f, position: i }))
    })
  }, [])

  // Toggle visibility
  const toggleVisibility = useCallback((index: number) => {
    setFields(prev =>
      prev.map((f, i) => (i === index ? { ...f, visible: !f.visible } : f))
    )
  }, [])

  // Set width
  const setWidth = useCallback((index: number, width: 25 | 33 | 50 | 100) => {
    setFields(prev =>
      prev.map((f, i) => (i === index ? { ...f, width } : f))
    )
  }, [])

  // Set height
  const setHeight = useCallback((index: number, height: 'small' | 'medium' | 'large') => {
    setFields(prev =>
      prev.map((f, i) => (i === index ? { ...f, height } : f))
    )
  }, [])

  // Save layout
  const handleSave = useCallback(async () => {
    if (!activeSchema || !activeTable) return

    setSaving(true)
    try {
      // Get existing layout to preserve list config
      const existing = layoutKey ? layouts[layoutKey] : null
      const config: LayoutConfig = {
        list: existing?.list ?? { columns: [] },
        detail: { fields },
      }
      await saveLayout(activeSchema, activeTable, config)
    } finally {
      setSaving(false)
    }
  }, [activeSchema, activeTable, fields, layoutKey, layouts, saveLayout])

  // Reset to defaults
  const handleReset = useCallback(() => {
    setFields(
      columns.map((col, i) => ({
        name: col.column_name,
        visible: true,
        position: i,
        width: 50,
        height: 'small',
      }))
    )
  }, [columns])

  // Don't render if no table is active
  if (!activeSchema || !activeTable || !columns.length) return null

  return (
    <>
      {/* Gear icon toggle button */}
      <button
        type="button"
        onClick={() => setOpen(prev => !prev)}
        className="p-1.5 rounded transition-colors hover:opacity-80"
        style={{
          color: open ? 'var(--color-primary)' : 'var(--color-text-muted)',
          backgroundColor: open ? 'color-mix(in srgb, var(--color-primary) 10%, transparent)' : 'transparent',
        }}
        aria-label="Layout settings"
        title="Layout settings"
      >
        <svg
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <circle cx="12" cy="12" r="3" />
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
        </svg>
      </button>

      {/* Settings panel overlay */}
      {open && (
        <div
          className="fixed top-0 right-0 h-full w-80 sm:w-96 z-50 flex flex-col shadow-xl"
          style={{
            backgroundColor: 'var(--color-surface)',
            borderLeft: '1px solid var(--color-border)',
          }}
        >
          {/* Panel header */}
          <div
            className="shrink-0 px-4 py-3 flex items-center justify-between border-b"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <h3
              className="text-sm font-semibold"
              style={{ color: 'var(--color-text)' }}
            >
              Detail Layout
            </h3>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="p-1 rounded hover:opacity-80 transition-opacity"
              style={{ color: 'var(--color-text-muted)' }}
              aria-label="Close settings"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>

          {/* Field list — scrollable */}
          <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2">
            {fields.map((field, index) => (
              <FieldConfigRow
                key={field.name}
                field={field}
                index={index}
                isFirst={index === 0}
                isLast={index === fields.length - 1}
                onMoveUp={() => moveUp(index)}
                onMoveDown={() => moveDown(index)}
                onToggleVisibility={() => toggleVisibility(index)}
                onSetWidth={(w) => setWidth(index, w)}
                onSetHeight={(h) => setHeight(index, h)}
              />
            ))}
          </div>

          {/* Footer with Save / Reset */}
          <div
            className="shrink-0 px-4 py-3 flex items-center gap-2 border-t"
            style={{ borderColor: 'var(--color-border)' }}
          >
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="flex-1 text-xs px-3 py-2 rounded font-medium transition-opacity disabled:opacity-50"
              style={{
                backgroundColor: 'var(--color-primary)',
                color: 'var(--color-on-primary, #fff)',
              }}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              type="button"
              onClick={handleReset}
              className="text-xs px-3 py-2 rounded font-medium transition-colors hover:opacity-80"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            >
              Reset
            </button>
          </div>
        </div>
      )}

      {/* Backdrop (click to close) */}
      {open && (
        <div
          className="fixed inset-0 z-40"
          style={{ backgroundColor: 'rgba(0, 0, 0, 0.3)' }}
          onClick={() => setOpen(false)}
          aria-hidden="true"
        />
      )}
    </>
  )
}

// ---- FieldConfigRow sub-component -----------------------------------------

interface FieldConfigRowProps {
  field: FieldConfig
  index: number
  isFirst: boolean
  isLast: boolean
  onMoveUp: () => void
  onMoveDown: () => void
  onToggleVisibility: () => void
  onSetWidth: (w: 25 | 33 | 50 | 100) => void
  onSetHeight: (h: 'small' | 'medium' | 'large') => void
}

function FieldConfigRow({
  field,
  index,
  isFirst,
  isLast,
  onMoveUp,
  onMoveDown,
  onToggleVisibility,
  onSetWidth,
  onSetHeight,
}: FieldConfigRowProps) {
  return (
    <div
      className="py-2 border-b last:border-b-0"
      style={{
        borderColor: 'var(--color-border)',
        opacity: field.visible ? 1 : 0.5,
      }}
    >
      {/* Top row: reorder arrows, name, visibility toggle */}
      <div className="flex items-center gap-1.5">
        {/* Move up/down arrows */}
        <div className="flex flex-col shrink-0">
          <button
            type="button"
            onClick={onMoveUp}
            disabled={isFirst}
            className="p-0.5 rounded disabled:opacity-20 hover:opacity-80 transition-opacity"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label={`Move ${field.name} up`}
            title="Move up"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="18 15 12 9 6 15" />
            </svg>
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            disabled={isLast}
            className="p-0.5 rounded disabled:opacity-20 hover:opacity-80 transition-opacity"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label={`Move ${field.name} down`}
            title="Move down"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
        </div>

        {/* Field name */}
        <span
          className="text-xs font-medium flex-1 truncate"
          style={{ color: 'var(--color-text)' }}
          title={field.name}
        >
          {field.name}
        </span>

        {/* Visibility toggle */}
        <button
          type="button"
          onClick={onToggleVisibility}
          className="shrink-0 p-1 rounded hover:opacity-80 transition-opacity"
          style={{
            color: field.visible ? 'var(--color-primary)' : 'var(--color-text-muted)',
          }}
          aria-label={field.visible ? `Hide ${field.name}` : `Show ${field.name}`}
          title={field.visible ? 'Visible (click to hide)' : 'Hidden (click to show)'}
        >
          {field.visible ? (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          ) : (
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
              <line x1="1" y1="1" x2="23" y2="23" />
            </svg>
          )}
        </button>
      </div>

      {/* Bottom row: width + height controls (only shown when visible) */}
      {field.visible && (
        <div className="flex items-center gap-2 mt-1.5 ml-7">
          {/* Width selector */}
          <div className="flex items-center gap-1">
            <span
              className="text-[10px]"
              style={{ color: 'var(--color-text-muted)' }}
            >
              W:
            </span>
            <select
              value={field.width}
              onChange={(e) => onSetWidth(Number(e.target.value) as 25 | 33 | 50 | 100)}
              className="text-[11px] rounded px-1 py-0.5 outline-none cursor-pointer"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
              aria-label={`Width for ${field.name}`}
            >
              {WIDTH_OPTIONS.map(opt => (
                <option key={opt.value} value={opt.value}>
                  {opt.label}
                </option>
              ))}
            </select>
          </div>

          {/* Height selector */}
          <div className="flex items-center gap-1">
            <span
              className="text-[10px]"
              style={{ color: 'var(--color-text-muted)' }}
            >
              H:
            </span>
            <div className="flex gap-0.5">
              {HEIGHT_OPTIONS.map(opt => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => onSetHeight(opt.value)}
                  className="text-[10px] px-1.5 py-0.5 rounded transition-colors"
                  style={{
                    backgroundColor:
                      field.height === opt.value
                        ? 'var(--color-primary)'
                        : 'var(--color-background)',
                    color:
                      field.height === opt.value
                        ? 'var(--color-on-primary, #fff)'
                        : 'var(--color-text-muted)',
                    border: `1px solid ${field.height === opt.value ? 'var(--color-primary)' : 'var(--color-border)'}`,
                  }}
                  aria-label={`Set ${field.name} height to ${opt.value}`}
                  title={opt.value}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
