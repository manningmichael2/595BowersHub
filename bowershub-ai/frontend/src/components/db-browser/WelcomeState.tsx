/**
 * WelcomeState — landing page for the DB Browser at `/db`.
 *
 * Shown when no table is selected. Displays summary stats (schema count,
 * table count, total row count) and a grid of schema cards with quick
 * navigation links to each table within.
 *
 * _Requirements: 1.4_
 */
import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDbBrowserStore } from '../../stores/db-browser'

export default function WelcomeState() {
  const schemas = useDbBrowserStore(s => s.schemas)
  const schemasLoading = useDbBrowserStore(s => s.schemasLoading)
  const navigate = useNavigate()

  // Compute summary stats from the schemas data
  const stats = useMemo(() => {
    let totalTables = 0
    let totalRows = 0
    for (const schema of schemas) {
      totalTables += schema.tables.length
      for (const table of schema.tables) {
        totalRows += table.row_count
      }
    }
    return { totalSchemas: schemas.length, totalTables, totalRows }
  }, [schemas])

  if (schemasLoading) {
    return (
      <div
        className="flex items-center justify-center h-full"
        style={{ color: 'var(--color-text-muted)' }}
      >
        Loading schemas…
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full overflow-y-auto p-4 sm:p-6">
      {/* Heading */}
      <div className="mb-6">
        <h1
          className="text-2xl font-semibold mb-1"
          style={{ color: 'var(--color-text)' }}
        >
          Database Browser
        </h1>
        <p
          className="text-sm"
          style={{ color: 'var(--color-text-muted)' }}
        >
          Browse and manage your data across all schemas.
        </p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-3 mb-6">
        <StatCard label="Schemas" value={stats.totalSchemas} />
        <StatCard label="Tables" value={stats.totalTables} />
        <StatCard label="Total Rows" value={formatNumber(stats.totalRows)} />
      </div>

      {/* Schema cards with table links */}
      {schemas.length === 0 ? (
        <div
          className="text-sm text-center py-8"
          style={{ color: 'var(--color-text-muted)' }}
        >
          No schemas found. Create one to get started.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {schemas.map(schema => (
            <SchemaCard
              key={schema.name}
              name={schema.name}
              tables={schema.tables}
              onTableClick={(table) => navigate(`/db/${schema.name}/${table}`)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div
      className="rounded-lg p-3 text-center"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div
        className="text-xl font-semibold"
        style={{ color: 'var(--color-text)' }}
      >
        {value}
      </div>
      <div
        className="text-xs mt-0.5"
        style={{ color: 'var(--color-text-muted)' }}
      >
        {label}
      </div>
    </div>
  )
}

function SchemaCard({
  name,
  tables,
  onTableClick,
}: {
  name: string
  tables: { name: string; row_count: number; has_link_table: boolean }[]
  onTableClick: (table: string) => void
}) {
  return (
    <div
      className="rounded-lg p-4"
      style={{
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
      }}
    >
      <div className="flex items-center justify-between mb-3">
        <h3
          className="text-sm font-medium"
          style={{ color: 'var(--color-text)' }}
        >
          {name}
        </h3>
        <span
          className="text-xs px-2 py-0.5 rounded-full"
          style={{
            backgroundColor: 'var(--color-primary)',
            color: 'var(--color-background)',
            opacity: 0.9,
          }}
        >
          {tables.length} {tables.length === 1 ? 'table' : 'tables'}
        </span>
      </div>

      {tables.length === 0 ? (
        <p
          className="text-xs italic"
          style={{ color: 'var(--color-text-muted)' }}
        >
          No tables
        </p>
      ) : (
        <ul className="space-y-1">
          {tables.map(table => (
            <li key={table.name}>
              <button
                type="button"
                onClick={() => onTableClick(table.name)}
                className="w-full text-left px-2 py-1.5 rounded text-sm transition-colors flex items-center justify-between gap-2 group"
                style={{ color: 'var(--color-text)' }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.backgroundColor = 'var(--color-background)'
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.backgroundColor = 'transparent'
                }}
              >
                <span className="flex items-center gap-1.5 min-w-0">
                  {table.has_link_table && (
                    <span className="text-xs shrink-0" title="Has image support">📷</span>
                  )}
                  <span className="truncate">{table.name}</span>
                </span>
                <span
                  className="text-xs shrink-0"
                  style={{ color: 'var(--color-text-muted)' }}
                >
                  {formatNumber(table.row_count)} rows
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

// ---- Helpers --------------------------------------------------------------

function formatNumber(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(n)
}
