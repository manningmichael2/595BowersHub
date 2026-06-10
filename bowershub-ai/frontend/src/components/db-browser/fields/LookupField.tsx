/**
 * LookupField — FK dropdown with type-ahead search.
 *
 * Renders a select dropdown populated from the referenced table via the
 * lookup-options API endpoint. Displays human-readable labels (name/title/
 * description priority, determined server-side). Shows a hyperlink icon to
 * navigate to the linked record.
 *
 * For tables with >200 options, switches to a text input with debounced
 * type-ahead search that queries the search endpoint on each keystroke.
 *
 * _Requirements: 8.10, 17.1, 17.2, 17.3, 17.5_
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../../services/api'
import type { ColumnMeta } from '../../../stores/db-browser'

// ---- Types ----------------------------------------------------------------

interface LookupOption {
  id: any
  label: string
}

export interface LookupFieldProps {
  value: any
  onChange: (value: any) => void
  compact?: boolean
  readOnly?: boolean
  column: ColumnMeta
  schema: string
  table: string
}

// ---- Constants ------------------------------------------------------------

const TYPE_AHEAD_THRESHOLD = 200
const DEBOUNCE_MS = 300

// ---- Component ------------------------------------------------------------

export default function LookupField({
  value,
  onChange,
  compact = false,
  readOnly = false,
  column,
  schema,
  table,
}: LookupFieldProps) {
  const navigate = useNavigate()

  const [options, setOptions] = useState<LookupOption[]>([])
  const [loading, setLoading] = useState(true)
  const [useTypeAhead, setUseTypeAhead] = useState(false)

  // Type-ahead state
  const [searchTerm, setSearchTerm] = useState('')
  const [searchResults, setSearchResults] = useState<LookupOption[]>([])
  const [searchLoading, setSearchLoading] = useState(false)
  const [showDropdown, setShowDropdown] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  // Build the API URL for this column's lookup options
  const lookupUrl = `/api/db/${encodeURIComponent(schema)}/${encodeURIComponent(table)}/lookup-options/${encodeURIComponent(column.column_name)}`

  // ---- Load options on mount ------------------------------------------------

  useEffect(() => {
    let cancelled = false

    async function fetchOptions() {
      setLoading(true)
      try {
        const res = await api.get(lookupUrl)
        if (cancelled) return
        const data: LookupOption[] = res.data ?? []
        setOptions(data)
        // Switch to type-ahead mode if too many options
        if (data.length > TYPE_AHEAD_THRESHOLD) {
          setUseTypeAhead(true)
        }
      } catch {
        if (!cancelled) {
          setOptions([])
        }
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    fetchOptions()
    return () => { cancelled = true }
  }, [lookupUrl])

  // ---- Type-ahead search with debounce --------------------------------------

  const doSearch = useCallback(async (term: string) => {
    if (!term.trim()) {
      setSearchResults([])
      setShowDropdown(false)
      return
    }
    setSearchLoading(true)
    try {
      const res = await api.get(`${lookupUrl}?search=${encodeURIComponent(term)}`)
      setSearchResults(res.data ?? [])
      setShowDropdown(true)
    } catch {
      setSearchResults([])
    } finally {
      setSearchLoading(false)
    }
  }, [lookupUrl])

  const handleSearchInput = (term: string) => {
    setSearchTerm(term)
    if (debounceRef.current) {
      clearTimeout(debounceRef.current)
    }
    debounceRef.current = setTimeout(() => {
      doSearch(term)
    }, DEBOUNCE_MS)
  }

  // ---- Close dropdown on outside click --------------------------------------

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setShowDropdown(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // ---- Cleanup debounce on unmount ------------------------------------------

  useEffect(() => {
    return () => {
      if (debounceRef.current) {
        clearTimeout(debounceRef.current)
      }
    }
  }, [])

  // ---- Helpers --------------------------------------------------------------

  /** Find the label for the current value in the loaded options. */
  function getCurrentLabel(): string {
    if (value == null) return ''
    const match = options.find(o => String(o.id) === String(value))
    return match ? match.label : String(value)
  }

  /** Navigate to the linked record's detail view. */
  function handleNavigateToLinked() {
    if (value == null || !column.fk_schema || !column.fk_table) return
    navigate(`/db/${column.fk_schema}/${column.fk_table}/${value}`)
  }

  // ---- Styles ---------------------------------------------------------------

  const baseInputStyle: React.CSSProperties = {
    backgroundColor: 'var(--color-background)',
    color: 'var(--color-text)',
    border: compact ? 'none' : '1px solid var(--color-border)',
    height: compact ? '36px' : undefined,
    padding: compact ? '0 4px' : undefined,
  }

  const inputClassName = compact
    ? 'w-full text-xs outline-none bg-transparent'
    : 'w-full text-xs outline-none rounded px-2 py-1.5'

  // ---- Loading state --------------------------------------------------------

  if (loading) {
    return (
      <span
        className="text-xs italic"
        style={{
          color: 'var(--color-text-muted)',
          lineHeight: compact ? '36px' : 'normal',
        }}
      >
        Loading…
      </span>
    )
  }

  // ---- Empty state ----------------------------------------------------------

  if (options.length === 0 && !useTypeAhead) {
    return (
      <span
        className="text-xs italic"
        style={{
          color: 'var(--color-text-muted)',
          lineHeight: compact ? '36px' : 'normal',
        }}
      >
        No options
      </span>
    )
  }

  // ---- Type-ahead mode (>200 rows) -----------------------------------------

  if (useTypeAhead) {
    return (
      <div className="flex items-center gap-1 w-full" ref={containerRef}>
        <div className="relative w-full">
          <input
            type="text"
            value={searchTerm || getCurrentLabel()}
            onChange={(e) => handleSearchInput(e.target.value)}
            onFocus={() => {
              // On focus, if we have a value label, put it in search term for editing
              if (!searchTerm && value != null) {
                setSearchTerm(getCurrentLabel())
              }
            }}
            disabled={readOnly}
            placeholder="Type to search…"
            style={baseInputStyle}
            className={inputClassName}
          />

          {/* Search loading indicator */}
          {searchLoading && (
            <span
              className="absolute right-2 top-1/2 -translate-y-1/2 text-xs"
              style={{ color: 'var(--color-text-muted)' }}
            >
              …
            </span>
          )}

          {/* Dropdown results */}
          {showDropdown && searchResults.length > 0 && (
            <div
              className="absolute z-50 left-0 right-0 mt-1 max-h-48 overflow-y-auto rounded shadow-lg text-xs"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                top: '100%',
              }}
            >
              {searchResults.map((opt) => (
                <button
                  key={String(opt.id)}
                  type="button"
                  className="w-full text-left px-2 py-1.5 hover:opacity-80"
                  style={{
                    color: 'var(--color-text)',
                    backgroundColor: String(opt.id) === String(value)
                      ? 'var(--color-primary)'
                      : 'transparent',
                  }}
                  onClick={() => {
                    onChange(opt.id)
                    setSearchTerm(opt.label)
                    setShowDropdown(false)
                  }}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          )}

          {/* No results message */}
          {showDropdown && searchResults.length === 0 && !searchLoading && searchTerm.trim() && (
            <div
              className="absolute z-50 left-0 right-0 mt-1 rounded shadow-lg text-xs px-2 py-1.5 italic"
              style={{
                backgroundColor: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-muted)',
                top: '100%',
              }}
            >
              No matches
            </div>
          )}
        </div>

        {/* Navigate to linked record (hidden in compact mode) */}
        {!compact && value != null && column.fk_schema && column.fk_table && (
          <button
            type="button"
            onClick={handleNavigateToLinked}
            className="shrink-0 text-xs hover:opacity-80"
            style={{ color: 'var(--color-primary)' }}
            title={`View ${column.fk_table} record`}
          >
            →
          </button>
        )}
      </div>
    )
  }

  // ---- Standard dropdown mode (≤200 rows) -----------------------------------

  return (
    <div className="flex items-center gap-1 w-full">
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        disabled={readOnly}
        style={baseInputStyle}
        className={inputClassName}
      >
        <option value="">—</option>
        {options.map((opt) => (
          <option key={String(opt.id)} value={opt.id}>
            {opt.label}
          </option>
        ))}
      </select>

      {/* Navigate to linked record (hidden in compact mode) */}
      {!compact && value != null && column.fk_schema && column.fk_table && (
        <button
          type="button"
          onClick={handleNavigateToLinked}
          className="shrink-0 text-xs hover:opacity-80"
          style={{ color: 'var(--color-primary)' }}
          title={`View ${column.fk_table} record`}
        >
          →
        </button>
      )}
    </div>
  )
}
