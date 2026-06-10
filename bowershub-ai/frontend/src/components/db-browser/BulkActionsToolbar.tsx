/**
 * BulkActionsToolbar — floating toolbar that appears when rows are selected.
 *
 * Shows the count of selected rows and provides action buttons:
 * - Delete: triggers bulk delete (opens confirmation dialog via parent)
 * - Edit Field: opens bulk edit dialog (task 16.3)
 * - Export CSV: exports selected rows as CSV (task 16.5)
 *
 * Positioned sticky at the bottom of the TableView with elevation/shadow.
 * Uses CSS custom properties for all colors.
 *
 * _Requirements: 27.1, 27.2, 27.3_
 */
import { useDbBrowserStore } from '../../stores/db-browser'

interface BulkActionsToolbarProps {
  onBulkDelete: () => void
  onBulkEdit: () => void
  onBulkExport: () => void
}

export default function BulkActionsToolbar({
  onBulkDelete,
  onBulkEdit,
  onBulkExport,
}: BulkActionsToolbarProps) {
  const selectedRows = useDbBrowserStore(s => s.selectedRows)
  const clearSelection = useDbBrowserStore(s => s.clearSelection)

  const count = selectedRows.size
  if (count === 0) return null

  return (
    <div
      className="sticky bottom-0 z-20 flex items-center justify-between gap-3 px-4 py-2 border-t"
      style={{
        backgroundColor: 'var(--color-surface)',
        borderColor: 'var(--color-border)',
        boxShadow: '0 -2px 8px rgba(0, 0, 0, 0.15)',
      }}
    >
      {/* Selection count + clear */}
      <div className="flex items-center gap-2">
        <span
          className="text-xs font-medium"
          style={{ color: 'var(--color-text)' }}
        >
          {count} row{count !== 1 ? 's' : ''} selected
        </span>
        <button
          type="button"
          onClick={clearSelection}
          className="text-xs px-1.5 py-0.5 rounded transition-opacity hover:opacity-80"
          style={{
            color: 'var(--color-text-muted)',
            border: '1px solid var(--color-border)',
          }}
          title="Clear selection"
        >
          ✕ Clear
        </button>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onBulkExport}
          className="text-xs px-2.5 py-1 rounded transition-opacity hover:opacity-80 flex items-center gap-1"
          style={{
            backgroundColor: 'var(--color-background)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
          title="Export selected rows as CSV"
        >
          <span>📄</span>
          <span className="hidden sm:inline">Export CSV</span>
        </button>

        <button
          type="button"
          onClick={onBulkEdit}
          className="text-xs px-2.5 py-1 rounded transition-opacity hover:opacity-80 flex items-center gap-1"
          style={{
            backgroundColor: 'var(--color-background)',
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
          }}
          title="Edit a field on all selected rows"
        >
          <span>✏️</span>
          <span className="hidden sm:inline">Edit Field</span>
        </button>

        <button
          type="button"
          onClick={onBulkDelete}
          className="text-xs px-2.5 py-1 rounded transition-opacity hover:opacity-80 flex items-center gap-1"
          style={{
            backgroundColor: 'var(--color-error)',
            color: 'var(--color-on-primary)',
          }}
          title="Delete selected rows"
        >
          <span>🗑️</span>
          <span className="hidden sm:inline">Delete</span>
        </button>
      </div>
    </div>
  )
}
