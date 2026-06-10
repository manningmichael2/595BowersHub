/**
 * RelationSections — displays related records from referencing tables
 * as expandable accordion sections below the main form in DetailView.
 *
 * Each section shows:
 * - Header: related table name + count badge (expandable)
 * - Body: compact mini-table with 3-4 key columns, max 5 rows
 * - "View all" link → navigates to related table pre-filtered by FK
 * - "Add" button → opens CreateRowDialog with FK field pre-filled and read-only
 *
 * _Requirements: 31.1, 31.2, 31.3, 31.4_
 */

import { useEffect, useState, useCallback, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDbBrowserStore, type RelationGroup } from '../../stores/db-browser'
import CreateRowDialog from './CreateRowDialog'

// ---- Props ----------------------------------------------------------------

interface RelationSectionsProps {
  schema: string
  table: string
  rowId: string
}

// ---- Constants ------------------------------------------------------------

/** Max columns to show in the compact mini-table */
const MAX_DISPLAY_COLUMNS = 4

// ---- Component ------------------------------------------------------------

export default function RelationSections({ schema, table, rowId }: RelationSectionsProps) {
  const navigate = useNavigate()
  const loadRelations = useDbBrowserStore(s => s.loadRelations)

  const [relations, setRelations] = useState<RelationGroup[]>([])
  const [loading, setLoading] = useState(true)
  const [expandedSections, setExpandedSections] = useState<Set<string>>(new Set())

  // CreateRowDialog state for the "Add" button
  const [addDialogOpen, setAddDialogOpen] = useState(false)
  const [addDialogTarget, setAddDialogTarget] = useState<{
    schema: string
    table: string
    fkColumn: string
  } | null>(null)

  // Fetch relations on mount or when row changes
  useEffect(() => {
    let cancelled = false

    const fetchRelations = async () => {
      setLoading(true)
      const data = await loadRelations(rowId)
      if (!cancelled) {
        setRelations(data)
        setLoading(false)
        // Auto-expand sections that have data
        const autoExpand = new Set<string>()
        data.forEach(r => {
          if (r.total_count > 0) {
            autoExpand.add(`${r.schema}.${r.table}`)
          }
        })
        setExpandedSections(autoExpand)
      }
    }

    fetchRelations()
    return () => { cancelled = true }
  }, [rowId, loadRelations])

  // Toggle section expansion
  const toggleSection = useCallback((key: string) => {
    setExpandedSections(prev => {
      const next = new Set(prev)
      if (next.has(key)) {
        next.delete(key)
      } else {
        next.add(key)
      }
      return next
    })
  }, [])

  // Navigate to related table pre-filtered
  const handleViewAll = useCallback((relation: RelationGroup) => {
    const filterParam = encodeURIComponent(
      JSON.stringify([{
        column: relation.fk_column,
        operator: 'eq',
        value: rowId,
      }])
    )
    navigate(`/db/${relation.schema}/${relation.table}?filters=${filterParam}`)
  }, [navigate, rowId])

  // Open CreateRowDialog for the related table with FK pre-filled
  const handleAdd = useCallback((relation: RelationGroup) => {
    setAddDialogTarget({
      schema: relation.schema,
      table: relation.table,
      fkColumn: relation.fk_column,
    })
    setAddDialogOpen(true)
  }, [])

  const handleCloseAddDialog = useCallback(() => {
    setAddDialogOpen(false)
    setAddDialogTarget(null)
  }, [])

  // Initial values for the CreateRowDialog — FK field pre-filled
  const addDialogInitialValues = useMemo(() => {
    if (!addDialogTarget) return undefined
    return { [addDialogTarget.fkColumn]: rowId }
  }, [addDialogTarget, rowId])

  // Read-only fields for the CreateRowDialog — FK field is locked
  const addDialogReadOnlyFields = useMemo(() => {
    if (!addDialogTarget) return undefined
    return new Set([addDialogTarget.fkColumn])
  }, [addDialogTarget])

  // Don't render anything if loading or no relations
  if (loading) {
    return (
      <div className="mt-6 max-w-4xl">
        <div
          className="text-xs py-2"
          style={{ color: 'var(--color-text-muted)' }}
        >
          Loading relations…
        </div>
      </div>
    )
  }

  if (relations.length === 0) return null

  return (
    <div className="mt-6 max-w-4xl">
      <h3
        className="text-xs font-semibold uppercase tracking-wide mb-3"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Related Records
      </h3>

      <div
        className="rounded-lg overflow-hidden"
        style={{ border: '1px solid var(--color-border)' }}
      >
        {relations.map((relation, idx) => {
          const sectionKey = `${relation.schema}.${relation.table}`
          const isExpanded = expandedSections.has(sectionKey)
          const isLast = idx === relations.length - 1

          return (
            <RelationAccordion
              key={sectionKey}
              relation={relation}
              isExpanded={isExpanded}
              isLast={isLast}
              onToggle={() => toggleSection(sectionKey)}
              onViewAll={() => handleViewAll(relation)}
              onAdd={() => handleAdd(relation)}
              currentRowId={rowId}
            />
          )
        })}
      </div>

      {/* CreateRowDialog for the "Add" action */}
      {addDialogTarget && (
        <CreateRowDialog
          open={addDialogOpen}
          onClose={handleCloseAddDialog}
          schema={addDialogTarget.schema}
          table={addDialogTarget.table}
          initialValues={addDialogInitialValues}
          readOnlyFields={addDialogReadOnlyFields}
        />
      )}
    </div>
  )
}

// ---- RelationAccordion sub-component --------------------------------------

interface RelationAccordionProps {
  relation: RelationGroup
  isExpanded: boolean
  isLast: boolean
  onToggle: () => void
  onViewAll: () => void
  onAdd: () => void
  currentRowId: string
}

function RelationAccordion({
  relation,
  isExpanded,
  isLast,
  onToggle,
  onViewAll,
  onAdd,
  currentRowId,
}: RelationAccordionProps) {
  // Determine which columns to show (first 3-4 key columns, excluding the FK column)
  const displayColumns = useMemo(() => {
    if (relation.rows.length === 0) return []

    const allKeys = Object.keys(relation.rows[0])
    // Exclude the FK column itself (it's always the current row ID — redundant)
    // and common auto-generated columns
    const excluded = new Set([
      relation.fk_column,
      'created_at',
      'updated_at',
      'archived_at',
    ])

    const candidates = allKeys.filter(k => !excluded.has(k))
    return candidates.slice(0, MAX_DISPLAY_COLUMNS)
  }, [relation])

  return (
    <div
      style={{
        borderBottom: isLast ? 'none' : '1px solid var(--color-border)',
      }}
    >
      {/* Accordion Header */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center justify-between px-3 py-2.5 text-left transition-colors hover:opacity-90"
        style={{ backgroundColor: 'var(--color-background)' }}
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2">
          {/* Chevron */}
          <svg
            width="14"
            height="14"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="shrink-0 transition-transform"
            style={{
              color: 'var(--color-text-muted)',
              transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
            }}
          >
            <polyline points="9 18 15 12 9 6" />
          </svg>

          {/* Table name */}
          <span
            className="text-xs font-medium"
            style={{ color: 'var(--color-text)' }}
          >
            {relation.schema !== 'public' && (
              <span style={{ color: 'var(--color-text-muted)' }}>
                {relation.schema}.
              </span>
            )}
            {relation.table}
          </span>

          {/* Count badge */}
          <span
            className="text-[10px] px-1.5 py-0.5 rounded-full font-medium"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
              opacity: relation.total_count > 0 ? 1 : 0.5,
            }}
          >
            {relation.total_count}
          </span>
        </div>

        {/* FK column indicator */}
        <span
          className="text-[10px]"
          style={{ color: 'var(--color-text-muted)' }}
        >
          via {relation.fk_column}
        </span>
      </button>

      {/* Accordion Body */}
      {isExpanded && (
        <div
          className="px-3 pb-3"
          style={{ backgroundColor: 'var(--color-surface)' }}
        >
          {relation.rows.length === 0 ? (
            <p
              className="text-xs py-2 italic"
              style={{ color: 'var(--color-text-muted)' }}
            >
              No related records
            </p>
          ) : (
            <>
              {/* Compact mini-table */}
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr>
                      {displayColumns.map(col => (
                        <th
                          key={col}
                          className="text-left py-1.5 px-2 font-medium whitespace-nowrap"
                          style={{
                            color: 'var(--color-text-muted)',
                            borderBottom: '1px solid var(--color-border)',
                          }}
                        >
                          {col.replace(/_/g, ' ')}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {relation.rows.map((row, rowIdx) => (
                      <tr
                        key={rowIdx}
                        className="transition-colors hover:opacity-80"
                      >
                        {displayColumns.map(col => (
                          <td
                            key={col}
                            className="py-1.5 px-2 truncate max-w-[200px]"
                            style={{
                              color: 'var(--color-text)',
                              borderBottom: rowIdx < relation.rows.length - 1
                                ? '1px solid var(--color-border)'
                                : 'none',
                            }}
                            title={row[col] != null ? String(row[col]) : '—'}
                          >
                            {formatCellValue(row[col])}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {/* Action buttons row */}
          <div className="flex items-center gap-3 mt-2 pt-2" style={{ borderTop: '1px solid var(--color-border)' }}>
            {/* View all link */}
            {relation.total_count > 5 && (
              <button
                type="button"
                onClick={onViewAll}
                className="text-[11px] font-medium hover:underline transition-opacity"
                style={{ color: 'var(--color-primary)' }}
              >
                View all {relation.total_count} →
              </button>
            )}

            {relation.total_count > 0 && relation.total_count <= 5 && (
              <button
                type="button"
                onClick={onViewAll}
                className="text-[11px] font-medium hover:underline transition-opacity"
                style={{ color: 'var(--color-primary)' }}
              >
                View in table →
              </button>
            )}

            {/* Add button */}
            <button
              type="button"
              onClick={onAdd}
              className="text-[11px] px-2 py-1 rounded font-medium transition-opacity hover:opacity-80"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            >
              + Add
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- Helpers --------------------------------------------------------------

/** Format a cell value for display in the compact mini-table */
function formatCellValue(value: any): string {
  if (value == null) return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (value instanceof Date) return value.toLocaleDateString()

  const str = String(value)
  // Truncate long strings
  if (str.length > 50) return str.slice(0, 47) + '…'
  return str
}
