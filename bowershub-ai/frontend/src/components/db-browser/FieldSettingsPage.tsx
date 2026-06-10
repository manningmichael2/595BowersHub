/**
 * FieldSettingsPage — full-page settings for configuring Field_Hints.
 *
 * Lists all columns across all user schemas with their current Field_Hint
 * configuration. Allows setting input type, prefix, suffix, min/max/step,
 * placeholder, and dropdown options per column name.
 *
 * After saving a hint, calls loadFieldHints() on the store so
 * SmartFieldRenderer picks up changes immediately without page reload.
 *
 * Requirements: 18.1, 18.2, 18.3, 18.5, 18.6
 */

import { useEffect, useState, useMemo } from 'react'
import { api } from '../../services/api'
import { useDbBrowserStore, FieldHint } from '../../stores/db-browser'
import { useIsAdmin } from '../../hooks/useIsAdmin'

type FilterMode = 'all' | 'configured' | 'unconfigured'

interface ColumnInfo {
  column_name: string
  tables: string[] // "schema.table" list
}

const INPUT_TYPES: FieldHint['input_type'][] = [
  'text', 'number', 'fraction', 'select', 'url', 'date', 'boolean', 'textarea'
]

function emptyHint(column_name: string): FieldHint {
  return {
    column_name,
    input_type: 'text',
    options: null,
    prefix: null,
    suffix: null,
    min_val: null,
    max_val: null,
    step: null,
    placeholder: null,
  }
}

export default function FieldSettingsPage() {
  const isAdmin = useIsAdmin()
  const schemas = useDbBrowserStore(s => s.schemas)
  const fieldHints = useDbBrowserStore(s => s.fieldHints)
  const loadFieldHints = useDbBrowserStore(s => s.loadFieldHints)

  const [allColumns, setAllColumns] = useState<ColumnInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterMode>('all')
  const [search, setSearch] = useState('')
  const [editingHints, setEditingHints] = useState<Record<string, FieldHint>>({})
  const [saving, setSaving] = useState<Record<string, boolean>>({})
  const [toasts, setToasts] = useState<{ id: number; msg: string; type: 'success' | 'error' }[]>([])

  // Fetch all columns from all schemas
  useEffect(() => {
    async function fetchColumns() {
      setLoading(true)
      try {
        const columnsMap: Record<string, string[]> = {}

        for (const schema of schemas) {
          for (const table of schema.tables) {
            try {
              const res = await api.get(`/api/db/${schema.name}/${table.name}/columns`)
              const cols: { column_name: string }[] = res.data
              for (const col of cols) {
                const key = col.column_name
                if (!columnsMap[key]) columnsMap[key] = []
                columnsMap[key].push(`${schema.name}.${table.name}`)
              }
            } catch {
              // Skip tables we can't read columns for
            }
          }
        }

        const result: ColumnInfo[] = Object.entries(columnsMap)
          .map(([column_name, tables]) => ({ column_name, tables }))
          .sort((a, b) => a.column_name.localeCompare(b.column_name))

        setAllColumns(result)
      } finally {
        setLoading(false)
      }
    }

    if (schemas.length > 0) {
      fetchColumns()
    }
  }, [schemas])

  // Filtered and searched columns
  const filteredColumns = useMemo(() => {
    let result = allColumns

    // Filter by configured/unconfigured
    if (filter === 'configured') {
      result = result.filter(c => fieldHints[c.column_name])
    } else if (filter === 'unconfigured') {
      result = result.filter(c => !fieldHints[c.column_name])
    }

    // Search by column name
    if (search.trim()) {
      const term = search.trim().toLowerCase()
      result = result.filter(c => c.column_name.toLowerCase().includes(term))
    }

    return result
  }, [allColumns, filter, search, fieldHints])

  function getEditHint(column_name: string): FieldHint {
    if (editingHints[column_name]) return editingHints[column_name]
    if (fieldHints[column_name]) return { ...fieldHints[column_name] }
    return emptyHint(column_name)
  }

  function updateEditHint(column_name: string, patch: Partial<FieldHint>) {
    const current = getEditHint(column_name)
    setEditingHints(prev => ({
      ...prev,
      [column_name]: { ...current, ...patch },
    }))
  }

  function showToast(msg: string, type: 'success' | 'error') {
    const id = Date.now()
    setToasts(prev => [...prev, { id, msg, type }])
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 3000)
  }

  async function saveHint(column_name: string) {
    const hint = getEditHint(column_name)
    setSaving(prev => ({ ...prev, [column_name]: true }))
    try {
      await api.put(`/api/db/field-hints/${encodeURIComponent(column_name)}`, {
        input_type: hint.input_type,
        options: hint.options,
        prefix: hint.prefix || null,
        suffix: hint.suffix || null,
        min_val: hint.min_val,
        max_val: hint.max_val,
        step: hint.step,
        placeholder: hint.placeholder || null,
      })
      // Refresh hints in the store so SmartFieldRenderer picks up changes immediately
      await loadFieldHints()
      // Clear local editing state for this column
      setEditingHints(prev => {
        const next = { ...prev }
        delete next[column_name]
        return next
      })
      showToast(`Saved hint for "${column_name}"`, 'success')
    } catch {
      showToast(`Failed to save hint for "${column_name}"`, 'error')
    } finally {
      setSaving(prev => ({ ...prev, [column_name]: false }))
    }
  }

  async function deleteHint(column_name: string) {
    setSaving(prev => ({ ...prev, [column_name]: true }))
    try {
      await api.delete(`/api/db/field-hints/${encodeURIComponent(column_name)}`)
      await loadFieldHints()
      setEditingHints(prev => {
        const next = { ...prev }
        delete next[column_name]
        return next
      })
      showToast(`Reverted "${column_name}" to default`, 'success')
    } catch {
      showToast(`Failed to delete hint for "${column_name}"`, 'error')
    } finally {
      setSaving(prev => ({ ...prev, [column_name]: false }))
    }
  }

  if (loading) {
    return (
      <div
        className="flex items-center justify-center h-full"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Loading columns…
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div
        className="shrink-0 px-4 py-3"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <h1 className="text-lg font-semibold mb-2" style={{ color: 'var(--color-text)' }}>
          Field Settings
        </h1>
        <p className="text-sm mb-3" style={{ color: 'var(--color-text-muted)' }}>
          Configure how columns render in the Smart Field system. Changes take effect immediately.
        </p>

        {/* Search + Filter row */}
        <div className="flex flex-wrap gap-2 items-center">
          {/* Search input */}
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search columns…"
            className="px-3 py-1.5 rounded text-sm flex-1 min-w-[200px]"
            style={{
              backgroundColor: 'var(--color-background)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
          />

          {/* Filter tabs */}
          <div className="flex rounded overflow-hidden" style={{ border: '1px solid var(--color-border)' }}>
            {(['all', 'configured', 'unconfigured'] as FilterMode[]).map(mode => (
              <button
                key={mode}
                onClick={() => setFilter(mode)}
                className="px-3 py-1.5 text-xs font-medium capitalize transition-colors"
                style={{
                  backgroundColor: filter === mode ? 'var(--color-primary)' : 'var(--color-background)',
                  color: filter === mode ? 'var(--color-on-primary, #fff)' : 'var(--color-text-muted)',
                }}
              >
                {mode}
              </button>
            ))}
          </div>

          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {filteredColumns.length} column{filteredColumns.length !== 1 ? 's' : ''}
          </span>
        </div>
      </div>

      {/* Column list */}
      <div className="flex-1 overflow-y-auto px-4 py-2">
        {filteredColumns.length === 0 && (
          <div className="text-center py-8" style={{ color: 'var(--color-text-muted)' }}>
            No columns match the current filter.
          </div>
        )}

        {filteredColumns.map(col => {
          const hint = getEditHint(col.column_name)
          const isConfigured = !!fieldHints[col.column_name]
          const isSaving = saving[col.column_name] || false

          return (
            <div
              key={col.column_name}
              className="mb-3 rounded p-3"
              style={{
                backgroundColor: 'var(--color-background)',
                border: '1px solid var(--color-border)',
              }}
            >
              {/* Column header */}
              <div className="flex items-center justify-between mb-2">
                <div>
                  <span className="font-medium text-sm" style={{ color: 'var(--color-text)' }}>
                    {col.column_name}
                  </span>
                  {isConfigured && (
                    <span
                      className="ml-2 text-xs px-1.5 py-0.5 rounded"
                      style={{
                        backgroundColor: 'var(--color-primary)',
                        color: 'var(--color-on-primary, #fff)',
                        opacity: 0.8,
                      }}
                    >
                      configured
                    </span>
                  )}
                </div>
                <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  {col.tables.length} table{col.tables.length !== 1 ? 's' : ''}
                </span>
              </div>

              {/* Tables this column appears in */}
              <div className="text-xs mb-2 flex flex-wrap gap-1" style={{ color: 'var(--color-text-muted)' }}>
                {col.tables.slice(0, 5).map(t => (
                  <span
                    key={t}
                    className="px-1.5 py-0.5 rounded"
                    style={{ backgroundColor: 'var(--color-surface)' }}
                  >
                    {t}
                  </span>
                ))}
                {col.tables.length > 5 && (
                  <span className="px-1.5 py-0.5">+{col.tables.length - 5} more</span>
                )}
              </div>

              {/* Config fields */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2">
                {/* Input type */}
                <label className="flex flex-col text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  <span className="mb-0.5">Input type</span>
                  <select
                    value={hint.input_type}
                    onChange={e => updateEditHint(col.column_name, { input_type: e.target.value as FieldHint['input_type'] })}
                    className="px-2 py-1 rounded text-sm"
                    style={{
                      backgroundColor: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  >
                    {INPUT_TYPES.map(t => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                </label>

                {/* Prefix */}
                <label className="flex flex-col text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  <span className="mb-0.5">Prefix</span>
                  <input
                    type="text"
                    value={hint.prefix || ''}
                    onChange={e => updateEditHint(col.column_name, { prefix: e.target.value || null })}
                    placeholder="e.g. $"
                    className="px-2 py-1 rounded text-sm"
                    style={{
                      backgroundColor: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  />
                </label>

                {/* Suffix */}
                <label className="flex flex-col text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  <span className="mb-0.5">Suffix</span>
                  <input
                    type="text"
                    value={hint.suffix || ''}
                    onChange={e => updateEditHint(col.column_name, { suffix: e.target.value || null })}
                    placeholder='e.g. °'
                    className="px-2 py-1 rounded text-sm"
                    style={{
                      backgroundColor: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  />
                </label>

                {/* Placeholder */}
                <label className="flex flex-col text-xs" style={{ color: 'var(--color-text-muted)' }}>
                  <span className="mb-0.5">Placeholder</span>
                  <input
                    type="text"
                    value={hint.placeholder || ''}
                    onChange={e => updateEditHint(col.column_name, { placeholder: e.target.value || null })}
                    placeholder="Placeholder text"
                    className="px-2 py-1 rounded text-sm"
                    style={{
                      backgroundColor: 'var(--color-surface)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                    }}
                  />
                </label>

                {/* Min (for numbers) */}
                {(hint.input_type === 'number' || hint.input_type === 'fraction') && (
                  <label className="flex flex-col text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    <span className="mb-0.5">Min</span>
                    <input
                      type="number"
                      value={hint.min_val ?? ''}
                      onChange={e => updateEditHint(col.column_name, { min_val: e.target.value ? Number(e.target.value) : null })}
                      className="px-2 py-1 rounded text-sm"
                      style={{
                        backgroundColor: 'var(--color-surface)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                      }}
                    />
                  </label>
                )}

                {/* Max (for numbers) */}
                {(hint.input_type === 'number' || hint.input_type === 'fraction') && (
                  <label className="flex flex-col text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    <span className="mb-0.5">Max</span>
                    <input
                      type="number"
                      value={hint.max_val ?? ''}
                      onChange={e => updateEditHint(col.column_name, { max_val: e.target.value ? Number(e.target.value) : null })}
                      className="px-2 py-1 rounded text-sm"
                      style={{
                        backgroundColor: 'var(--color-surface)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                      }}
                    />
                  </label>
                )}

                {/* Step (for numbers) */}
                {(hint.input_type === 'number' || hint.input_type === 'fraction') && (
                  <label className="flex flex-col text-xs" style={{ color: 'var(--color-text-muted)' }}>
                    <span className="mb-0.5">Step</span>
                    <input
                      type="number"
                      value={hint.step ?? ''}
                      onChange={e => updateEditHint(col.column_name, { step: e.target.value ? Number(e.target.value) : null })}
                      className="px-2 py-1 rounded text-sm"
                      style={{
                        backgroundColor: 'var(--color-surface)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                      }}
                    />
                  </label>
                )}

                {/* Options (for select type) */}
                {hint.input_type === 'select' && (
                  <label className="flex flex-col text-xs sm:col-span-2 lg:col-span-4" style={{ color: 'var(--color-text-muted)' }}>
                    <span className="mb-0.5">Dropdown options (one per line)</span>
                    <textarea
                      value={(hint.options || []).join('\n')}
                      onChange={e => {
                        const lines = e.target.value.split('\n')
                        updateEditHint(col.column_name, { options: lines.length === 1 && lines[0] === '' ? null : lines })
                      }}
                      rows={3}
                      className="px-2 py-1 rounded text-sm resize-y"
                      style={{
                        backgroundColor: 'var(--color-surface)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                      }}
                      placeholder="option1&#10;option2&#10;option3"
                    />
                  </label>
                )}
              </div>

              {/* Actions — hidden for non-admin (Req 21.3) */}
              {isAdmin && (
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => saveHint(col.column_name)}
                  disabled={isSaving}
                  className="px-3 py-1 rounded text-xs font-medium transition-opacity"
                  style={{
                    backgroundColor: 'var(--color-primary)',
                    color: 'var(--color-on-primary, #fff)',
                    opacity: isSaving ? 0.6 : 1,
                  }}
                >
                  {isSaving ? 'Saving…' : 'Save'}
                </button>
                {isConfigured && (
                  <button
                    onClick={() => deleteHint(col.column_name)}
                    disabled={isSaving}
                    className="px-3 py-1 rounded text-xs font-medium transition-opacity"
                    style={{
                      backgroundColor: 'transparent',
                      color: 'var(--color-text-muted)',
                      border: '1px solid var(--color-border)',
                      opacity: isSaving ? 0.6 : 1,
                    }}
                  >
                    Revert to default
                  </button>
                )}
              </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Toast notifications */}
      {toasts.length > 0 && (
        <div className="fixed bottom-4 right-4 flex flex-col gap-2 z-50">
          {toasts.map(t => (
            <div
              key={t.id}
              className="px-4 py-2 rounded shadow-lg text-sm font-medium"
              style={{
                backgroundColor: t.type === 'success' ? 'var(--color-primary)' : 'var(--color-error)',
                color: 'var(--color-on-primary)',
              }}
            >
              {t.msg}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
