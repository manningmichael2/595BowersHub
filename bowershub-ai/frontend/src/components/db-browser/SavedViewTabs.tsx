/**
 * SavedViewTabs — tab bar above the table for switching between saved views.
 *
 * Features:
 * - Default "All" tab (undeletable) that clears all filters/sort
 * - One tab per saved view for the current table
 * - Clicking a tab applies stored filters, sort, and column visibility
 * - "+ Save View" button prompts for a name and persists current config
 * - Right-click (or long-press) context menu on tabs for Rename and Delete
 * - "All" tab's context menu is disabled (undeletable)
 *
 * _Requirements: 28.1, 28.2, 28.3, 28.5_
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useDbBrowserStore, type SavedView } from '../../stores/db-browser'

export default function SavedViewTabs() {
  const views = useDbBrowserStore(s => s.views)
  const activeViewId = useDbBrowserStore(s => s.activeViewId)
  const activateView = useDbBrowserStore(s => s.activateView)
  const saveView = useDbBrowserStore(s => s.saveView)
  const renameView = useDbBrowserStore(s => s.renameView)
  const deleteView = useDbBrowserStore(s => s.deleteView)
  const filters = useDbBrowserStore(s => s.filters)
  const sortColumn = useDbBrowserStore(s => s.sortColumn)
  const sortDirection = useDbBrowserStore(s => s.sortDirection)

  // Save view dialog state
  const [saveDialogOpen, setSaveDialogOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saving, setSaving] = useState(false)

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    viewId: string
    x: number
    y: number
  } | null>(null)

  // Rename dialog state
  const [renameTarget, setRenameTarget] = useState<SavedView | null>(null)
  const [renameValue, setRenameValue] = useState('')

  const contextMenuRef = useRef<HTMLDivElement>(null)
  const saveInputRef = useRef<HTMLInputElement>(null)
  const renameInputRef = useRef<HTMLInputElement>(null)

  // Focus the save input when the dialog opens
  useEffect(() => {
    if (saveDialogOpen && saveInputRef.current) {
      saveInputRef.current.focus()
    }
  }, [saveDialogOpen])

  // Focus the rename input when the dialog opens
  useEffect(() => {
    if (renameTarget && renameInputRef.current) {
      renameInputRef.current.focus()
    }
  }, [renameTarget])

  // Close context menu on outside click or Escape
  useEffect(() => {
    if (!contextMenu) return
    function handleClick(e: MouseEvent) {
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target as Node)) {
        setContextMenu(null)
      }
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setContextMenu(null)
    }
    document.addEventListener('mousedown', handleClick)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handleClick)
      document.removeEventListener('keydown', handleKey)
    }
  }, [contextMenu])

  // Determine if there's something worth saving (active filters/sort)
  const hasActiveConfig = filters.length > 0 || sortColumn !== null

  const handleSave = useCallback(async () => {
    const name = saveName.trim()
    if (!name) return
    setSaving(true)
    try {
      await saveView(name)
      setSaveName('')
      setSaveDialogOpen(false)
    } finally {
      setSaving(false)
    }
  }, [saveName, saveView])

  const handleRename = useCallback(async () => {
    if (!renameTarget) return
    const name = renameValue.trim()
    if (!name || name === renameTarget.name) {
      setRenameTarget(null)
      return
    }
    await renameView(renameTarget.id, name)
    setRenameTarget(null)
  }, [renameTarget, renameValue, renameView])

  const handleDelete = useCallback(async (viewId: string) => {
    setContextMenu(null)
    await deleteView(viewId)
  }, [deleteView])

  const handleContextMenu = useCallback((e: React.MouseEvent, viewId: string) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ viewId, x: e.clientX, y: e.clientY })
  }, [])

  return (
    <div
      className="shrink-0 flex items-center gap-1 px-4 py-1.5 overflow-x-auto border-b"
      style={{
        borderColor: 'var(--color-border)',
        backgroundColor: 'var(--color-surface)',
      }}
    >
      {/* "All" tab — always first, undeletable */}
      <TabButton
        label="All"
        isActive={activeViewId === null}
        onClick={() => activateView(null)}
        onContextMenu={undefined}
      />

      {/* Saved view tabs */}
      {views.map(view => (
        <TabButton
          key={view.id}
          label={view.name}
          isActive={activeViewId === view.id}
          onClick={() => activateView(view.id)}
          onContextMenu={(e) => handleContextMenu(e, view.id)}
        />
      ))}

      {/* Save View button */}
      <button
        type="button"
        onClick={() => setSaveDialogOpen(true)}
        className="shrink-0 text-xs px-2 py-1 rounded transition-colors ml-1"
        style={{
          color: hasActiveConfig ? 'var(--color-primary)' : 'var(--color-text-muted)',
          backgroundColor: 'transparent',
          border: '1px dashed var(--color-border)',
        }}
        title={hasActiveConfig ? 'Save current filters/sort as a named view' : 'Apply filters or sort first to save a view'}
      >
        + Save View
      </button>

      {/* Context menu (Rename / Delete) */}
      {contextMenu && (
        <div
          ref={contextMenuRef}
          className="fixed z-[999] rounded shadow-lg py-1 min-w-[120px]"
          style={{
            left: contextMenu.x,
            top: contextMenu.y,
            backgroundColor: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
          }}
        >
          <button
            type="button"
            className="w-full text-left text-xs px-3 py-1.5 transition-colors"
            style={{ color: 'var(--color-text)' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-background)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
            onClick={() => {
              const view = views.find(v => v.id === contextMenu.viewId)
              if (view) {
                setRenameTarget(view)
                setRenameValue(view.name)
              }
              setContextMenu(null)
            }}
          >
            Rename
          </button>
          <button
            type="button"
            className="w-full text-left text-xs px-3 py-1.5 transition-colors"
            style={{ color: 'var(--color-error, #ef4444)' }}
            onMouseEnter={(e) => (e.currentTarget.style.backgroundColor = 'var(--color-background)')}
            onMouseLeave={(e) => (e.currentTarget.style.backgroundColor = 'transparent')}
            onClick={() => handleDelete(contextMenu.viewId)}
          >
            Delete
          </button>
        </div>
      )}

      {/* Save View dialog (inline prompt) */}
      {saveDialogOpen && (
        <div className="fixed inset-0 z-[998] flex items-center justify-center bg-black/40">
          <div
            className="rounded-lg shadow-xl p-4 w-[300px]"
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
            }}
          >
            <h3
              className="text-sm font-semibold mb-3"
              style={{ color: 'var(--color-text)' }}
            >
              Save View
            </h3>
            <input
              ref={saveInputRef}
              type="text"
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSave()
                if (e.key === 'Escape') setSaveDialogOpen(false)
              }}
              placeholder="View name..."
              className="w-full text-sm rounded px-2 py-1.5 outline-none mb-3"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setSaveDialogOpen(false)}
                className="text-xs px-3 py-1.5 rounded"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSave}
                disabled={!saveName.trim() || saving}
                className="text-xs px-3 py-1.5 rounded font-medium disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: 'var(--color-on-primary, #fff)',
                }}
              >
                {saving ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Rename dialog */}
      {renameTarget && (
        <div className="fixed inset-0 z-[998] flex items-center justify-center bg-black/40">
          <div
            className="rounded-lg shadow-xl p-4 w-[300px]"
            style={{
              backgroundColor: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
            }}
          >
            <h3
              className="text-sm font-semibold mb-3"
              style={{ color: 'var(--color-text)' }}
            >
              Rename View
            </h3>
            <input
              ref={renameInputRef}
              type="text"
              value={renameValue}
              onChange={(e) => setRenameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleRename()
                if (e.key === 'Escape') setRenameTarget(null)
              }}
              placeholder="New name..."
              className="w-full text-sm rounded px-2 py-1.5 outline-none mb-3"
              style={{
                backgroundColor: 'var(--color-background)',
                color: 'var(--color-text)',
                border: '1px solid var(--color-border)',
              }}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setRenameTarget(null)}
                className="text-xs px-3 py-1.5 rounded"
                style={{ color: 'var(--color-text-muted)' }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleRename}
                disabled={!renameValue.trim()}
                className="text-xs px-3 py-1.5 rounded font-medium disabled:opacity-50"
                style={{
                  backgroundColor: 'var(--color-primary)',
                  color: 'var(--color-on-primary, #fff)',
                }}
              >
                Rename
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

interface TabButtonProps {
  label: string
  isActive: boolean
  onClick: () => void
  onContextMenu: ((e: React.MouseEvent) => void) | undefined
}

function TabButton({ label, isActive, onClick, onContextMenu }: TabButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      onContextMenu={onContextMenu}
      className="shrink-0 text-xs px-2.5 py-1 rounded transition-colors whitespace-nowrap"
      style={{
        backgroundColor: isActive ? 'var(--color-primary)' : 'transparent',
        color: isActive ? 'var(--color-on-primary, #fff)' : 'var(--color-text)',
        border: isActive ? 'none' : '1px solid var(--color-border)',
        fontWeight: isActive ? 500 : 400,
      }}
    >
      {label}
    </button>
  )
}
