/**
 * FilterBuilder — multi-condition filter panel for the table view.
 *
 * Renders a dropdown panel with filter condition rows. Each condition has
 * a column selector, operator selector, value input (hidden for is_null/has_value),
 * and a remove button. Supports adding new conditions, applying all at once,
 * and clearing all filters.
 *
 * _Requirements: 5.1, 5.2, 5.4_
 */
import { useState, useRef, useEffect } from 'react'
import { useDbBrowserStore, type FilterCondition, type ColumnMeta } from '../../stores/db-browser'

const OPERATORS: { value: FilterCondition['operator']; label: string }[] = [
  { value: 'eq', label: 'Equals' },
  { value: 'neq', label: 'Not equals' },
  { value: 'contains', label: 'Contains' },
  { value: 'gt', label: 'Greater than' },
  { value: 'lt', label: 'Less than' },
  { value: 'is_null', label: 'Is null' },
  { value: 'has_value', label: 'Has value' },
]

const VALUE_HIDDEN_OPERATORS: FilterCondition['operator'][] = ['is_null', 'has_value']

export default function FilterBuilder() {
  const columns = useDbBrowserStore(s => s.columns)
  const storeFilters = useDbBrowserStore(s => s.filters)
  const setFilters = useDbBrowserStore(s => s.setFilters)

  const [open, setOpen] = useState(false)
  const [localConditions, setLocalConditions] = useState<FilterCondition[]>([])
  const panelRef = useRef<HTMLDivElement>(null)

  // Sync local state when the panel opens or store filters change externally
  useEffect(() => {
    if (open) {
      setLocalConditions(storeFilters.length > 0 ? [...storeFilters] : [])
    }
  }, [open, storeFilters])

  // Close panel on outside click
  useEffect(() => {
    if (!open) return
    function handleClick(e: MouseEvent) {
      if (panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  function addCondition() {
    const defaultCol = columns.length > 0 ? columns[0].column_name : ''
    setLocalConditions(prev => [
      ...prev,
      { column: defaultCol, operator: 'eq', value: '' },
    ])
  }

  function removeCondition(index: number) {
    setLocalConditions(prev => prev.filter((_, i) => i !== index))
  }

  function updateCondition(index: number, field: keyof FilterCondition, value: string) {
    setLocalConditions(prev =>
      prev.map((cond, i) => {
        if (i !== index) return cond
        const updated = { ...cond, [field]: value }
        // Clear value when switching to a valueless operator
        if (field === 'operator' && VALUE_HIDDEN_OPERATORS.includes(value as FilterCondition['operator'])) {
          updated.value = ''
        }
        return updated
      })
    )
  }

  function handleApply() {
    // Filter out empty conditions (no column selected)
    const valid = localConditions.filter(c => c.column)
    setFilters(valid)
    setOpen(false)
  }

  function handleClear() {
    setLocalConditions([])
    setFilters([])
    setOpen(false)
  }

  const activeCount = storeFilters.length

  return (
    <div className="relative" ref={panelRef}>
      {/* Filter toggle button with badge */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="relative flex items-center gap-1 text-xs px-2 py-1 rounded transition-colors"
        style={{
          backgroundColor: activeCount > 0 ? 'var(--color-primary)' : 'var(--color-background)',
          color: activeCount > 0 ? 'var(--color-on-primary, #fff)' : 'var(--color-text)',
          border: '1px solid var(--color-border)',
        }}
      >
        <FilterIcon />
        <span>Filter</span>
        {activeCount > 0 && (
          <span
            className="inline-flex items-center justify-center text-[10px] font-bold rounded-full w-4 h-4"
            style={{
              backgroundColor: 'var(--color-background)',
              color: 'var(--color-primary)',
            }}
          >
            {activeCount}
          </span>
        )}
      </button>

      {/* Filter panel dropdown */}
      {open && (
        <div
          className="absolute left-0 top-full mt-1 z-50 rounded-lg shadow-lg p-3 min-w-[360px] max-w-[500px]"
          style={{
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          {/* Conditions list */}
          <div className="space-y-2 mb-3 max-h-[300px] overflow-y-auto">
            {localConditions.length === 0 && (
              <p
                className="text-xs italic py-2"
                style={{ color: 'var(--color-text-muted)' }}
              >
                No filter conditions. Click "Add condition" to start filtering.
              </p>
            )}
            {localConditions.map((cond, index) => (
              <FilterRow
                key={index}
                condition={cond}
                columns={columns}
                onChange={(field, value) => updateCondition(index, field, value)}
                onRemove={() => removeCondition(index)}
              />
            ))}
          </div>

          {/* Action buttons */}
          <div className="flex items-center justify-between gap-2 pt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
            <button
              type="button"
              onClick={addCondition}
              className="text-xs px-2 py-1 rounded transition-colors"
              style={{
                color: 'var(--color-primary)',
                backgroundColor: 'transparent',
              }}
            >
              + Add condition
            </button>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleClear}
                className="text-xs px-2 py-1 rounded transition-colors"
                style={{
                  color: 'var(--color-text-muted)',
                  backgroundColor: 'transparent',
                }}
              >
                Clear
              </button>
              <button
                type="button"
                onClick={handleApply}
                className="text-xs px-3 py-1 rounded transition-colors font-medium"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: 'var(--color-on-primary, #fff)',
                }}
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

interface FilterRowProps {
  condition: FilterCondition
  columns: ColumnMeta[]
  onChange: (field: keyof FilterCondition, value: string) => void
  onRemove: () => void
}

function FilterRow({ condition, columns, onChange, onRemove }: FilterRowProps) {
  const hideValue = VALUE_HIDDEN_OPERATORS.includes(condition.operator)

  return (
    <div className="flex items-center gap-1.5">
      {/* Column selector */}
      <select
        value={condition.column}
        onChange={(e) => onChange('column', e.target.value)}
        className="text-xs rounded px-1.5 py-1 min-w-[100px] outline-none"
        style={{
          backgroundColor: 'var(--color-background)',
          color: 'var(--color-text)',
          border: '1px solid var(--color-border)',
        }}
      >
        {columns.map(col => (
          <option key={col.column_name} value={col.column_name}>
            {col.column_name}
          </option>
        ))}
      </select>

      {/* Operator selector */}
      <select
        value={condition.operator}
        onChange={(e) => onChange('operator', e.target.value)}
        className="text-xs rounded px-1.5 py-1 min-w-[90px] outline-none"
        style={{
          backgroundColor: 'var(--color-background)',
          color: 'var(--color-text)',
          border: '1px solid var(--color-border)',
        }}
      >
        {OPERATORS.map(op => (
          <option key={op.value} value={op.value}>
            {op.label}
          </option>
        ))}
      </select>

      {/* Value input (hidden for is_null / has_value) */}
      {!hideValue && (
        <input
          type="text"
          value={condition.value}
          onChange={(e) => onChange('value', e.target.value)}
          placeholder="Value..."
          className="text-xs rounded px-1.5 py-1 flex-1 min-w-[80px] outline-none"
          style={{
            backgroundColor: 'var(--color-background)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
        />
      )}

      {/* Remove button */}
      <button
        type="button"
        onClick={onRemove}
        className="shrink-0 w-5 h-5 flex items-center justify-center rounded text-xs transition-colors"
        style={{
          color: 'var(--color-text-muted)',
          backgroundColor: 'transparent',
        }}
        title="Remove condition"
      >
        ✕
      </button>
    </div>
  )
}

// ---- Icons ----------------------------------------------------------------

function FilterIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M1.5 3h13M4 8h8M6.5 13h3" strokeLinecap="round" />
    </svg>
  )
}
