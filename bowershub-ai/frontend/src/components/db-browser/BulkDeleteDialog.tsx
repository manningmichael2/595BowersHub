/**
 * BulkDeleteDialog — modal confirmation dialog for bulk row deletion.
 *
 * Shows the exact count of rows to be deleted with a warning message.
 * On confirmation, calls bulkDelete(Array.from(selectedRows)) from the store.
 * On success, closes the dialog (selection is cleared and rows reloaded by the store action).
 * Dismissible via Cancel button, backdrop click, or Escape key.
 *
 * Props: { open, onClose }. Reads selectedRows from the store.
 * Uses CSS custom properties for all styling.
 *
 * _Requirements: 27.4_
 */

import { useState, useEffect, useCallback } from 'react'
import { useDbBrowserStore } from '../../stores/db-browser'

interface BulkDeleteDialogProps {
  open: boolean
  onClose: () => void
}

export default function BulkDeleteDialog({ open, onClose }: BulkDeleteDialogProps) {
  const selectedRows = useDbBrowserStore(s => s.selectedRows)
  const bulkDelete = useDbBrowserStore(s => s.bulkDelete)

  const [deleting, setDeleting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Reset state when dialog opens
  useEffect(() => {
    if (open) {
      setDeleting(false)
      setError(null)
    }
  }, [open])

  // Close on Escape key
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  const handleConfirm = useCallback(async () => {
    setDeleting(true)
    setError(null)

    try {
      await bulkDelete(Array.from(selectedRows))
      onClose()
    } catch (err: any) {
      const message =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Failed to delete rows'
      setError(message)
    } finally {
      setDeleting(false)
    }
  }, [bulkDelete, selectedRows, onClose])

  if (!open) return null

  const count = selectedRows.size

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div
        className="rounded-lg p-5 max-w-sm w-full mx-4 shadow-xl"
        style={{
          backgroundColor: 'var(--color-surface)',
          color: 'var(--color-text)',
          border: '1px solid var(--color-border)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Title */}
        <h3 className="text-sm font-semibold mb-2">
          Delete {count} row{count !== 1 ? 's' : ''}?
        </h3>

        {/* Warning message */}
        <p
          className="text-xs mb-4"
          style={{ color: 'var(--color-text-muted)' }}
        >
          This will permanently delete {count} selected row{count !== 1 ? 's' : ''}.
          This action cannot be undone.
        </p>

        {/* Error message */}
        {error && (
          <p
            className="text-xs mb-3 px-2 py-1.5 rounded"
            style={{
              backgroundColor: 'color-mix(in srgb, var(--color-error) 10%, transparent)',
              color: 'var(--color-error)',
              border: '1px solid color-mix(in srgb, var(--color-error) 30%, transparent)',
            }}
          >
            {error}
          </p>
        )}

        {/* Action buttons */}
        <div className="flex gap-2 justify-end">
          <button
            type="button"
            onClick={onClose}
            disabled={deleting}
            className="text-xs px-3 py-1.5 rounded transition-opacity hover:opacity-80"
            style={{
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={deleting}
            className="text-xs px-3 py-1.5 rounded transition-opacity hover:opacity-90 disabled:opacity-50"
            style={{ backgroundColor: 'var(--color-error)', color: 'var(--color-on-primary)' }}
          >
            {deleting ? 'Deleting…' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  )
}
