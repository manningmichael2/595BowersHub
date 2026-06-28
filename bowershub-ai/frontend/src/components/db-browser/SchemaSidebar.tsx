/**
 * SchemaSidebar — left-panel navigation for the DB Browser.
 *
 * Displays schemas as collapsible accordions with tables listed alphabetically
 * within each group. Tables with image support (link table) show a camera icon.
 * The active table is highlighted and clicking navigates to its Table_View.
 *
 * On mobile (< 640px), the sidebar collapses into an overlay drawer toggled
 * by a hamburger button rendered in the main area header.
 *
 * Includes schema management actions:
 * - "New Schema" button (+ icon) at the top prompts for a schema name
 * - "New Table" button opens CreateTableDialog (when available)
 * - Right-click context menu on tables: Rename, Move to Schema, Add Column, Delete Column
 *
 * _Requirements: 2.2, 2.4, 2.5, 15.1, 16.1, 23.1_
 */

import { useState, useMemo, useEffect, useRef, useCallback } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useDbBrowserStore } from '../../stores/db-browser'
import { useSettingsStore } from '../../stores/settings'
import { useIsAdmin } from '../../hooks/useIsAdmin'
import { api } from '../../services/api'

/** A "schema.table" preference key (favorites / hidden are stored as these). */
const tkey = (schema: string, table: string) => `${schema}.${table}`

interface TableMeta {
  name: string
  column_count: number
  row_count: number
  has_link_table: boolean
}

interface SchemaLike { name: string; tables: TableMeta[] }

const byName = (a: { name: string }, b: { name: string }) =>
  a.name.localeCompare(b.name, undefined, { sensitivity: 'base' })

/** Resolve favorite "schema.table" keys to concrete tables (skipping stale keys),
 * filtered by the search query, sorted by table name. Pure — unit-tested. */
export function buildFavoriteEntries(
  schemas: SchemaLike[], favorites: Set<string>, q: string,
): { schema: string; table: TableMeta }[] {
  const out: { schema: string; table: TableMeta }[] = []
  for (const s of schemas) {
    for (const t of s.tables) {
      if (favorites.has(tkey(s.name, t.name)) && (q === '' || t.name.toLowerCase().includes(q))) {
        out.push({ schema: s.name, table: t })
      }
    }
  }
  return out.sort((a, b) => byName(a.table, b.table))
}

/** Per-schema visible tables: hidden filtered out (unless showHidden), search
 * applied, sorted. Groups with no matches under an active search are dropped.
 * Pure — unit-tested. */
export function buildSchemaGroups(
  schemas: SchemaLike[], hidden: Set<string>, showHidden: boolean, q: string,
): { name: string; tables: TableMeta[]; hiddenCount: number }[] {
  return schemas
    .map(schema => {
      const tables = [...schema.tables]
        .filter(t => showHidden || !hidden.has(tkey(schema.name, t.name)))
        .filter(t => q === '' || t.name.toLowerCase().includes(q))
        .sort(byName)
      const hiddenCount = schema.tables.filter(t => hidden.has(tkey(schema.name, t.name))).length
      return { name: schema.name, tables, hiddenCount }
    })
    .filter(g => q === '' || g.tables.length > 0)
}

interface SchemaSidebarProps {
  /** Whether the mobile drawer is open (controlled by parent) */
  mobileOpen: boolean
  /** Callback to close the mobile drawer */
  onMobileClose: () => void
}

// ---- Context Menu Types ---------------------------------------------------

interface ContextMenuState {
  visible: boolean
  x: number
  y: number
  schemaName: string
  tableName: string
}

// ---- Modal/Dialog Types ---------------------------------------------------

type DialogMode =
  | { type: 'none' }
  | { type: 'new-schema' }
  | { type: 'rename-table'; schema: string; table: string }
  | { type: 'move-table'; schema: string; table: string }
  | { type: 'add-column'; schema: string; table: string }
  | { type: 'delete-column'; schema: string; table: string }

export default function SchemaSidebar({ mobileOpen, onMobileClose }: SchemaSidebarProps) {
  const isAdmin = useIsAdmin()
  const schemas = useDbBrowserStore(s => s.schemas)
  const schemasLoading = useDbBrowserStore(s => s.schemasLoading)
  const loadSchemas = useDbBrowserStore(s => s.loadSchemas)
  const { schema: activeSchema, table: activeTable } = useParams<{
    schema: string
    table: string
  }>()
  const navigate = useNavigate()

  // Per-user sidebar prefs (favorites / hidden / expanded schemas), persisted in
  // settings_json via the settings store (synced across devices).
  const settings = useSettingsStore(s => s.settings)
  const patchSettings = useSettingsStore(s => s.patch)
  const favorites = useMemo(() => new Set(settings.db_favorites ?? []), [settings.db_favorites])
  const hidden = useMemo(() => new Set(settings.db_hidden ?? []), [settings.db_hidden])

  // Search filter + "show hidden" toggle (ephemeral, not persisted).
  const [search, setSearch] = useState('')
  const [showHidden, setShowHidden] = useState(false)
  const q = search.trim().toLowerCase()

  // Context menu state
  const [contextMenu, setContextMenu] = useState<ContextMenuState>({
    visible: false,
    x: 0,
    y: 0,
    schemaName: '',
    tableName: '',
  })

  // Dialog state
  const [dialog, setDialog] = useState<DialogMode>({ type: 'none' })

  // Collapse-by-default: a schema is open only if the user expanded it
  // (persisted). First-load default opens just the active schema; once the user
  // toggles anything, db_expanded is authoritative.
  const expandedSet = useMemo(
    () => new Set(settings.db_expanded ?? (activeSchema ? [activeSchema] : [])),
    [settings.db_expanded, activeSchema],
  )

  const persist = useCallback((delta: { db_favorites?: string[]; db_hidden?: string[]; db_expanded?: string[] }) => {
    void patchSettings(delta).catch(() => {})
  }, [patchSettings])

  const toggleSchema = (name: string) => {
    const next = new Set(expandedSet)
    if (next.has(name)) next.delete(name); else next.add(name)
    persist({ db_expanded: [...next] })
  }

  const toggleFavorite = (schema: string, table: string) => {
    const next = new Set(favorites)
    const k = tkey(schema, table)
    if (next.has(k)) next.delete(k); else next.add(k)
    persist({ db_favorites: [...next] })
  }

  const toggleHidden = (schema: string, table: string) => {
    const next = new Set(hidden)
    const k = tkey(schema, table)
    if (next.has(k)) next.delete(k); else next.add(k)
    persist({ db_hidden: [...next] })
  }

  // Favorites pinned at top; schema groups with hidden/search applied. Pure
  // helpers (buildFavoriteEntries / buildSchemaGroups) are unit-tested.
  const favoriteEntries = useMemo(
    () => buildFavoriteEntries(schemas, favorites, q),
    [schemas, favorites, q],
  )
  const groups = useMemo(
    () => buildSchemaGroups(schemas, hidden, showHidden, q),
    [schemas, hidden, showHidden, q],
  )

  const totalHidden = hidden.size

  const handleTableClick = (schemaName: string, tableName: string) => {
    navigate(`/db/${schemaName}/${tableName}`)
    onMobileClose()
  }

  const handleTableContextMenu = (
    e: React.MouseEvent,
    schemaName: string,
    tableName: string
  ) => {
    e.preventDefault()
    setContextMenu({
      visible: true,
      x: e.clientX,
      y: e.clientY,
      schemaName,
      tableName,
    })
  }

  const closeContextMenu = useCallback(() => {
    setContextMenu(prev => ({ ...prev, visible: false }))
  }, [])

  const handleNewSchema = () => {
    setDialog({ type: 'new-schema' })
  }

  const handleNewTable = () => {
    // For now, navigate to a create-table route or open a dialog
    // CreateTableDialog will be rendered at the page level when it exists
    navigate('/db?action=create-table')
  }

  const sidebarContent = (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div
        className="shrink-0 px-4 py-3 flex items-center justify-between"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <h2
          className="text-sm font-semibold uppercase tracking-wide"
          style={{ color: 'var(--color-text-muted)' }}
        >
          Schemas
        </h2>
        <div className="flex items-center gap-1">
          {/* New Schema button — hidden for non-admin (Req 21.3) */}
          {isAdmin && (
          <button
            type="button"
            onClick={handleNewSchema}
            className="p-1.5 rounded transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
            onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'var(--color-surface)' }}
            onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent' }}
            aria-label="New Schema"
            title="New Schema"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <circle cx="12" cy="12" r="10" />
              <line x1="12" y1="8" x2="12" y2="16" />
              <line x1="8" y1="12" x2="16" y2="12" />
            </svg>
          </button>
          )}
          {/* New Table button — hidden for non-admin (Req 21.3) */}
          {isAdmin && (
          <button
            type="button"
            onClick={handleNewTable}
            className="p-1.5 rounded transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
            onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'var(--color-surface)' }}
            onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent' }}
            aria-label="New Table"
            title="New Table"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <rect x="3" y="3" width="18" height="18" rx="2" />
              <line x1="12" y1="8" x2="12" y2="16" />
              <line x1="8" y1="12" x2="16" y2="12" />
            </svg>
          </button>
          )}
          {/* Close button — visible only in mobile overlay — touch-friendly (Req 23.4) */}
          <button
            type="button"
            onClick={onMobileClose}
            className="sm:hidden p-2.5 rounded transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
            style={{ color: 'var(--color-text-muted)' }}
            aria-label="Close sidebar"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      </div>

      {/* Search / filter */}
      <div className="shrink-0 px-2 pt-2">
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Filter tables…"
          aria-label="Filter tables"
          className="w-full px-2.5 py-1.5 rounded text-sm"
          style={{
            backgroundColor: 'var(--color-background)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        />
      </div>

      {/* Schema list */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2">
        {schemasLoading ? (
          <p className="text-sm px-2 py-4" style={{ color: 'var(--color-text-muted)' }}>
            Loading schemas…
          </p>
        ) : schemas.length === 0 ? (
          <p className="text-sm px-2 py-4" style={{ color: 'var(--color-text-muted)' }}>
            No schemas found.
          </p>
        ) : (
          <div className="space-y-1">
            {/* Favorites — pinned at top, always visible */}
            {favoriteEntries.length > 0 && (
              <FavoritesGroup
                entries={favoriteEntries}
                activeSchema={activeSchema}
                activeTable={activeTable}
                onTableClick={handleTableClick}
                onToggleFavorite={toggleFavorite}
              />
            )}

            {groups.map(group => (
              <SchemaGroup
                key={group.name}
                name={group.name}
                tables={group.tables}
                hiddenCount={group.hiddenCount}
                isExpanded={q !== '' || expandedSet.has(group.name)}
                activeSchema={activeSchema}
                activeTable={activeTable}
                favorites={favorites}
                hidden={hidden}
                onToggle={() => toggleSchema(group.name)}
                onTableClick={handleTableClick}
                onTableContextMenu={handleTableContextMenu}
                onToggleFavorite={toggleFavorite}
                onToggleHidden={toggleHidden}
              />
            ))}

            {q !== '' && favoriteEntries.length === 0 && groups.length === 0 && (
              <p className="text-sm px-2 py-4" style={{ color: 'var(--color-text-muted)' }}>
                No tables match “{search}”.
              </p>
            )}
          </div>
        )}
      </div>

      {/* Show/hide hidden-tables toggle */}
      {totalHidden > 0 && (
        <div className="shrink-0 px-3 py-1.5" style={{ borderTop: '1px solid var(--color-border)' }}>
          <button
            type="button"
            onClick={() => setShowHidden(v => !v)}
            className="text-xs w-full text-left px-1 py-1 rounded"
            style={{ color: 'var(--color-text-muted)' }}
          >
            {showHidden ? '▾ Hide hidden tables' : `▸ Show hidden (${totalHidden})`}
          </button>
        </div>
      )}

      {/* Field Settings link */}
      <div
        className="shrink-0 px-3 py-2"
        style={{ borderTop: '1px solid var(--color-border)' }}
      >
        <button
          type="button"
          onClick={() => { navigate('/db/inbox'); onMobileClose() }}
          className="flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm transition-colors"
          style={{ color: 'var(--color-text-muted)' }}
          onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'var(--color-surface)' }}
          onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent' }}
        >
          <span className="text-sm">📥</span>
          Inbox
        </button>
        <button
          type="button"
          onClick={() => { navigate('/db/settings'); onMobileClose() }}
          className="flex items-center gap-2 w-full px-2 py-1.5 rounded text-sm transition-colors"
          style={{ color: 'var(--color-text-muted)' }}
          onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'var(--color-surface)' }}
          onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent' }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <circle cx="12" cy="12" r="3" />
            <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
          </svg>
          Field Settings
        </button>
      </div>
    </div>
  )

  return (
    <>
      {/* Desktop sidebar — always visible at sm+ */}
      <aside
        className="shrink-0 overflow-hidden hidden sm:flex sm:flex-col"
        style={{
          width: '260px',
          backgroundColor: 'var(--color-background)',
          borderRight: '1px solid var(--color-border)',
        }}
      >
        {sidebarContent}
      </aside>

      {/* Mobile overlay drawer — visible below sm when open */}
      {mobileOpen && (
        <MobileDrawer onClose={onMobileClose}>
          {sidebarContent}
        </MobileDrawer>
      )}

      {/* Context menu */}
      {contextMenu.visible && (
        <TableContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          schemaName={contextMenu.schemaName}
          tableName={contextMenu.tableName}
          onClose={closeContextMenu}
          onRename={() => {
            setDialog({ type: 'rename-table', schema: contextMenu.schemaName, table: contextMenu.tableName })
            closeContextMenu()
          }}
          onMoveToSchema={() => {
            setDialog({ type: 'move-table', schema: contextMenu.schemaName, table: contextMenu.tableName })
            closeContextMenu()
          }}
          onAddColumn={() => {
            setDialog({ type: 'add-column', schema: contextMenu.schemaName, table: contextMenu.tableName })
            closeContextMenu()
          }}
          onDeleteColumn={() => {
            setDialog({ type: 'delete-column', schema: contextMenu.schemaName, table: contextMenu.tableName })
            closeContextMenu()
          }}
        />
      )}

      {/* Dialogs */}
      {dialog.type === 'new-schema' && (
        <NewSchemaDialog
          onClose={() => setDialog({ type: 'none' })}
          onSuccess={() => { setDialog({ type: 'none' }); loadSchemas() }}
        />
      )}
      {dialog.type === 'rename-table' && (
        <RenameTableDialog
          schema={dialog.schema}
          table={dialog.table}
          onClose={() => setDialog({ type: 'none' })}
          onSuccess={() => { setDialog({ type: 'none' }); loadSchemas() }}
        />
      )}
      {dialog.type === 'move-table' && (
        <MoveTableDialog
          schema={dialog.schema}
          table={dialog.table}
          schemas={schemas.map(s => s.name)}
          onClose={() => setDialog({ type: 'none' })}
          onSuccess={() => { setDialog({ type: 'none' }); loadSchemas() }}
        />
      )}
      {dialog.type === 'add-column' && (
        <AddColumnDialog
          schema={dialog.schema}
          table={dialog.table}
          onClose={() => setDialog({ type: 'none' })}
          onSuccess={() => { setDialog({ type: 'none' }); loadSchemas() }}
        />
      )}
      {dialog.type === 'delete-column' && (
        <DeleteColumnDialog
          schema={dialog.schema}
          table={dialog.table}
          onClose={() => setDialog({ type: 'none' })}
          onSuccess={() => { setDialog({ type: 'none' }); loadSchemas() }}
        />
      )}
    </>
  )
}

// ---- Sub-components -------------------------------------------------------

function MobileDrawer({
  children,
  onClose,
}: {
  children: React.ReactNode
  onClose: () => void
}) {
  const drawerRef = useRef<HTMLDivElement>(null)

  // Close on Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 sm:hidden">
      {/* Backdrop */}
      <div
        className="absolute inset-0"
        style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
        onClick={onClose}
        aria-hidden="true"
      />
      {/* Drawer panel */}
      <div
        ref={drawerRef}
        className="absolute inset-y-0 left-0 w-[280px] max-w-[80vw] shadow-xl"
        style={{ backgroundColor: 'var(--color-background)' }}
      >
        {children}
      </div>
    </div>
  )
}

// ---- Icons ----------------------------------------------------------------

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"
      fill={filled ? 'currentColor' : 'none'} strokeLinecap="round" strokeLinejoin="round">
      <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2" />
    </svg>
  )
}

function EyeIcon({ off }: { off: boolean }) {
  return off ? (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  ) : (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  )
}

// ---- Table row (shared by favorites + schema groups) ----------------------

function TableRow({
  schema, table, isActive, isFavorite, isHidden, schemaSuffix,
  onClick, onContextMenu, onToggleFavorite, onToggleHidden,
}: {
  schema: string
  table: TableMeta
  isActive: boolean
  isFavorite: boolean
  isHidden: boolean
  /** Show the schema name on the right (used in the cross-schema Favorites group). */
  schemaSuffix?: boolean
  onClick: () => void
  onContextMenu?: (e: React.MouseEvent) => void
  onToggleFavorite: () => void
  onToggleHidden?: () => void
}) {
  // Affordances: always tappable on mobile (no hover); hover-revealed on desktop.
  // A favorited star stays visible so "unfavorite" is always discoverable.
  const affordanceCls = 'flex items-center gap-0.5 pr-1 shrink-0 transition-opacity ' +
    (isFavorite ? 'opacity-100 ' : 'opacity-100 sm:opacity-0 sm:group-hover/row:opacity-100')
  return (
    <li>
      <div
        className="group/row flex items-center rounded transition-colors min-h-[44px] sm:min-h-0"
        style={{ backgroundColor: isActive ? 'var(--color-surface)' : 'transparent' }}
        onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.backgroundColor = 'var(--color-surface)' }}
        onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.backgroundColor = 'transparent' }}
      >
        <button
          type="button"
          onClick={onClick}
          onContextMenu={onContextMenu}
          className="flex-1 min-w-0 flex items-center gap-1.5 px-2 py-2.5 sm:py-1.5 text-left text-sm"
          style={{
            color: isActive ? 'var(--color-primary)' : isHidden ? 'var(--color-text-muted)' : 'var(--color-text)',
            fontWeight: isActive ? 500 : 400,
          }}
        >
          {table.has_link_table && <span className="text-xs shrink-0" title="Image support">📷</span>}
          {/* overflow-x-hidden (not `truncate`) so the ellipsis still clips
              horizontally but descenders (g/p/y) aren't clipped vertically. */}
          <span className="whitespace-nowrap overflow-x-hidden text-ellipsis">{table.name}</span>
          {schemaSuffix && (
            <span className="text-xs ml-1 shrink-0 whitespace-nowrap overflow-x-hidden text-ellipsis" style={{ color: 'var(--color-text-muted)' }}>
              {schema}
            </span>
          )}
        </button>
        <div className={affordanceCls}>
          <button
            type="button"
            onClick={onToggleFavorite}
            className="p-1 rounded"
            style={{ color: isFavorite ? 'var(--color-warning, #eab308)' : 'var(--color-text-muted)' }}
            aria-label={isFavorite ? `Unfavorite ${table.name}` : `Favorite ${table.name}`}
            title={isFavorite ? 'Unfavorite' : 'Favorite'}
          >
            <StarIcon filled={isFavorite} />
          </button>
          {onToggleHidden && (
            <button
              type="button"
              onClick={onToggleHidden}
              className="p-1 rounded"
              style={{ color: 'var(--color-text-muted)' }}
              aria-label={isHidden ? `Unhide ${table.name}` : `Hide ${table.name}`}
              title={isHidden ? 'Unhide' : 'Hide'}
            >
              <EyeIcon off={!isHidden} />
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

// ---- Favorites group (pinned at top, cross-schema) ------------------------

function FavoritesGroup({
  entries, activeSchema, activeTable, onTableClick, onToggleFavorite,
}: {
  entries: { schema: string; table: TableMeta }[]
  activeSchema: string | undefined
  activeTable: string | undefined
  onTableClick: (schema: string, table: string) => void
  onToggleFavorite: (schema: string, table: string) => void
}) {
  return (
    <div>
      <div className="flex items-center gap-1.5 px-2 py-1.5" style={{ color: 'var(--color-text-muted)' }}>
        <span style={{ color: 'var(--color-warning, #eab308)' }}><StarIcon filled /></span>
        <span className="text-xs font-semibold uppercase tracking-wide">Favorites</span>
      </div>
      <ul className="ml-3 mt-0.5 space-y-0.5">
        {entries.map(({ schema, table }) => (
          <TableRow
            key={`${schema}.${table.name}`}
            schema={schema}
            table={table}
            schemaSuffix
            isActive={activeSchema === schema && activeTable === table.name}
            isFavorite
            isHidden={false}
            onClick={() => onTableClick(schema, table.name)}
            onToggleFavorite={() => onToggleFavorite(schema, table.name)}
          />
        ))}
      </ul>
      <div className="mx-2 my-1" style={{ borderBottom: '1px solid var(--color-border)' }} />
    </div>
  )
}

// ---- Schema group ---------------------------------------------------------

function SchemaGroup({
  name,
  tables,
  hiddenCount,
  isExpanded,
  activeSchema,
  activeTable,
  favorites,
  hidden,
  onToggle,
  onTableClick,
  onTableContextMenu,
  onToggleFavorite,
  onToggleHidden,
}: {
  name: string
  tables: TableMeta[]
  hiddenCount: number
  isExpanded: boolean
  activeSchema: string | undefined
  activeTable: string | undefined
  favorites: Set<string>
  hidden: Set<string>
  onToggle: () => void
  onTableClick: (schema: string, table: string) => void
  onTableContextMenu: (e: React.MouseEvent, schema: string, table: string) => void
  onToggleFavorite: (schema: string, table: string) => void
  onToggleHidden: (schema: string, table: string) => void
}) {
  const isAdmin = useIsAdmin()
  return (
    <div>
      {/* Schema header — clickable to expand/collapse — touch-friendly (Req 23.4) */}
      <button
        type="button"
        onClick={onToggle}
        className="w-full flex items-center gap-1.5 px-2 py-2.5 sm:py-1.5 rounded text-left transition-colors min-h-[44px] sm:min-h-0"
        style={{ color: 'var(--color-text)' }}
        onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'var(--color-surface)' }}
        onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent' }}
      >
        <svg
          width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round"
          className="shrink-0 transition-transform"
          style={{
            color: 'var(--color-text-muted)',
            transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
          }}
        >
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span className="text-sm font-medium whitespace-nowrap overflow-x-hidden text-ellipsis">{name}</span>
        <span className="text-xs ml-auto shrink-0" style={{ color: 'var(--color-text-muted)' }}>
          {tables.length}{hiddenCount > 0 ? ` (+${hiddenCount})` : ''}
        </span>
      </button>

      {isExpanded && (
        <ul className="ml-3 mt-0.5 space-y-0.5">
          {tables.map(table => {
            const k = tkey(name, table.name)
            return (
              <TableRow
                key={table.name}
                schema={name}
                table={table}
                isActive={activeSchema === name && activeTable === table.name}
                isFavorite={favorites.has(k)}
                isHidden={hidden.has(k)}
                onClick={() => onTableClick(name, table.name)}
                onContextMenu={isAdmin ? (e) => onTableContextMenu(e, name, table.name) : undefined}
                onToggleFavorite={() => onToggleFavorite(name, table.name)}
                onToggleHidden={() => onToggleHidden(name, table.name)}
              />
            )
          })}
        </ul>
      )}
    </div>
  )
}

// ---- Context Menu ---------------------------------------------------------

function TableContextMenu({
  x,
  y,
  schemaName,
  tableName,
  onClose,
  onRename,
  onMoveToSchema,
  onAddColumn,
  onDeleteColumn,
}: {
  x: number
  y: number
  schemaName: string
  tableName: string
  onClose: () => void
  onRename: () => void
  onMoveToSchema: () => void
  onAddColumn: () => void
  onDeleteColumn: () => void
}) {
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose()
      }
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('mousedown', handleClickOutside)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleClickOutside)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  // Adjust position to keep menu within viewport
  const adjustedX = Math.min(x, window.innerWidth - 200)
  const adjustedY = Math.min(y, window.innerHeight - 200)

  const menuItems = [
    { label: 'Rename', action: onRename },
    { label: 'Move to Schema', action: onMoveToSchema },
    { label: 'Add Column', action: onAddColumn },
    { label: 'Delete Column', action: onDeleteColumn },
  ]

  return (
    <div
      ref={menuRef}
      className="fixed z-[100] py-1 rounded shadow-lg"
      style={{
        left: adjustedX,
        top: adjustedY,
        backgroundColor: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        minWidth: '160px',
      }}
    >
      <div
        className="px-3 py-1.5 text-xs truncate"
        style={{ color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border)' }}
      >
        {schemaName}.{tableName}
      </div>
      {menuItems.map(item => (
        <button
          key={item.label}
          type="button"
          onClick={item.action}
          className="w-full text-left px-3 py-2 text-sm transition-colors"
          style={{ color: 'var(--color-text)' }}
          onMouseEnter={e => { e.currentTarget.style.backgroundColor = 'var(--color-background)' }}
          onMouseLeave={e => { e.currentTarget.style.backgroundColor = 'transparent' }}
        >
          {item.label}
        </button>
      ))}
    </div>
  )
}

// ---- Dialogs --------------------------------------------------------------

function DialogOverlay({
  children,
  onClose,
}: {
  children: React.ReactNode
  onClose: () => void
}) {
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center">
      <div
        className="absolute inset-0"
        style={{ backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
        onClick={onClose}
      />
      <div
        className="relative z-10 rounded-lg shadow-xl p-5 w-[90vw] max-w-md"
        style={{
          backgroundColor: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
        }}
      >
        {children}
      </div>
    </div>
  )
}

function NewSchemaDialog({
  onClose,
  onSuccess,
}: {
  onClose: () => void
  onSuccess: () => void
}) {
  const [name, setName] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = name.trim()
    if (!trimmed) {
      setError('Schema name is required')
      return
    }
    if (!/^[a-z_][a-z0-9_]*$/.test(trimmed)) {
      setError('Schema name must start with a letter/underscore and contain only lowercase letters, numbers, underscores')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.post('/api/db/schemas', { name: trimmed })
      onSuccess()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to create schema')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogOverlay onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3 className="text-base font-semibold mb-3" style={{ color: 'var(--color-text)' }}>
          New Schema
        </h3>
        <input
          type="text"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="schema_name"
          autoFocus
          className="w-full px-3 py-2 rounded text-sm mb-2"
          style={{
            backgroundColor: 'var(--color-background)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        />
        {error && (
          <p className="text-xs mb-2" style={{ color: 'var(--color-error, #ef4444)' }}>{error}</p>
        )}
        <div className="flex justify-end gap-2 mt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="px-3 py-1.5 text-sm rounded font-medium"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? 'Creating…' : 'Create'}
          </button>
        </div>
      </form>
    </DialogOverlay>
  )
}

function RenameTableDialog({
  schema,
  table,
  onClose,
  onSuccess,
}: {
  schema: string
  table: string
  onClose: () => void
  onSuccess: () => void
}) {
  const [newName, setNewName] = useState(table)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = newName.trim()
    if (!trimmed) {
      setError('Table name is required')
      return
    }
    if (trimmed === table) {
      onClose()
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.patch(`/api/db/tables/${schema}/${table}`, { action: 'rename', new_name: trimmed })
      onSuccess()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to rename table')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogOverlay onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3 className="text-base font-semibold mb-3" style={{ color: 'var(--color-text)' }}>
          Rename Table
        </h3>
        <p className="text-xs mb-2" style={{ color: 'var(--color-text-muted)' }}>
          {schema}.{table}
        </p>
        <input
          type="text"
          value={newName}
          onChange={e => setNewName(e.target.value)}
          placeholder="new_table_name"
          autoFocus
          className="w-full px-3 py-2 rounded text-sm mb-2"
          style={{
            backgroundColor: 'var(--color-background)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        />
        {error && (
          <p className="text-xs mb-2" style={{ color: 'var(--color-error, #ef4444)' }}>{error}</p>
        )}
        <div className="flex justify-end gap-2 mt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="px-3 py-1.5 text-sm rounded font-medium"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? 'Renaming…' : 'Rename'}
          </button>
        </div>
      </form>
    </DialogOverlay>
  )
}

function MoveTableDialog({
  schema,
  table,
  schemas,
  onClose,
  onSuccess,
}: {
  schema: string
  table: string
  schemas: string[]
  onClose: () => void
  onSuccess: () => void
}) {
  const [targetSchema, setTargetSchema] = useState(schema)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const otherSchemas = schemas.filter(s => s !== schema)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (targetSchema === schema) {
      onClose()
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.patch(`/api/db/tables/${schema}/${table}`, { action: 'move', new_schema: targetSchema })
      onSuccess()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to move table')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogOverlay onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3 className="text-base font-semibold mb-3" style={{ color: 'var(--color-text)' }}>
          Move Table to Schema
        </h3>
        <p className="text-xs mb-2" style={{ color: 'var(--color-text-muted)' }}>
          {schema}.{table}
        </p>
        {otherSchemas.length === 0 ? (
          <p className="text-sm mb-2" style={{ color: 'var(--color-text-muted)' }}>
            No other schemas available. Create a new schema first.
          </p>
        ) : (
          <select
            value={targetSchema}
            onChange={e => setTargetSchema(e.target.value)}
            className="w-full px-3 py-2 rounded text-sm mb-2"
            style={{
              backgroundColor: 'var(--color-background)',
              border: '1px solid var(--color-border)',
              color: 'var(--color-text)',
            }}
          >
            {otherSchemas.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        )}
        {error && (
          <p className="text-xs mb-2" style={{ color: 'var(--color-error, #ef4444)' }}>{error}</p>
        )}
        <div className="flex justify-end gap-2 mt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading || otherSchemas.length === 0}
            className="px-3 py-1.5 text-sm rounded font-medium"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
              opacity: (loading || otherSchemas.length === 0) ? 0.6 : 1,
            }}
          >
            {loading ? 'Moving…' : 'Move'}
          </button>
        </div>
      </form>
    </DialogOverlay>
  )
}

function AddColumnDialog({
  schema,
  table,
  onClose,
  onSuccess,
}: {
  schema: string
  table: string
  onClose: () => void
  onSuccess: () => void
}) {
  const [columnName, setColumnName] = useState('')
  const [dataType, setDataType] = useState('text')
  const [nullable, setNullable] = useState(true)
  const [defaultValue, setDefaultValue] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const dataTypes = [
    { value: 'text', label: 'Text' },
    { value: 'integer', label: 'Integer' },
    { value: 'numeric', label: 'Decimal' },
    { value: 'boolean', label: 'Boolean' },
    { value: 'date', label: 'Date' },
    { value: 'timestamptz', label: 'Timestamp' },
  ]

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const trimmed = columnName.trim()
    if (!trimmed) {
      setError('Column name is required')
      return
    }
    if (!/^[a-z_][a-z0-9_]*$/.test(trimmed)) {
      setError('Column name must be lowercase with letters, numbers, underscores')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.patch(`/api/db/tables/${schema}/${table}`, {
        action: 'add_column',
        column_name: trimmed,
        column_type: dataType,
        nullable,
        default_value: defaultValue || null,
      })
      onSuccess()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to add column')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogOverlay onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3 className="text-base font-semibold mb-3" style={{ color: 'var(--color-text)' }}>
          Add Column
        </h3>
        <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
          {schema}.{table}
        </p>

        {/* Column name */}
        <label className="block text-xs mb-1" style={{ color: 'var(--color-text-muted)' }}>
          Column Name
        </label>
        <input
          type="text"
          value={columnName}
          onChange={e => setColumnName(e.target.value)}
          placeholder="column_name"
          autoFocus
          className="w-full px-3 py-2 rounded text-sm mb-3"
          style={{
            backgroundColor: 'var(--color-background)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        />

        {/* Data type */}
        <label className="block text-xs mb-1" style={{ color: 'var(--color-text-muted)' }}>
          Data Type
        </label>
        <select
          value={dataType}
          onChange={e => setDataType(e.target.value)}
          className="w-full px-3 py-2 rounded text-sm mb-3"
          style={{
            backgroundColor: 'var(--color-background)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        >
          {dataTypes.map(dt => (
            <option key={dt.value} value={dt.value}>{dt.label}</option>
          ))}
        </select>

        {/* Nullable toggle */}
        <label className="flex items-center gap-2 text-sm mb-3" style={{ color: 'var(--color-text)' }}>
          <input
            type="checkbox"
            checked={nullable}
            onChange={e => setNullable(e.target.checked)}
          />
          Nullable
        </label>

        {/* Default value */}
        <label className="block text-xs mb-1" style={{ color: 'var(--color-text-muted)' }}>
          Default Value (optional)
        </label>
        <input
          type="text"
          value={defaultValue}
          onChange={e => setDefaultValue(e.target.value)}
          placeholder="e.g. 0, 'pending', now()"
          className="w-full px-3 py-2 rounded text-sm mb-2"
          style={{
            backgroundColor: 'var(--color-background)',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text)',
          }}
        />

        {error && (
          <p className="text-xs mb-2" style={{ color: 'var(--color-error, #ef4444)' }}>{error}</p>
        )}
        <div className="flex justify-end gap-2 mt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="px-3 py-1.5 text-sm rounded font-medium"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'var(--color-on-primary, #fff)',
              opacity: loading ? 0.6 : 1,
            }}
          >
            {loading ? 'Adding…' : 'Add Column'}
          </button>
        </div>
      </form>
    </DialogOverlay>
  )
}

function DeleteColumnDialog({
  schema,
  table,
  onClose,
  onSuccess,
}: {
  schema: string
  table: string
  onClose: () => void
  onSuccess: () => void
}) {
  const [columns, setColumns] = useState<string[]>([])
  const [selectedColumn, setSelectedColumn] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [columnsLoading, setColumnsLoading] = useState(true)

  // Fetch columns for this table (exclude PK)
  useEffect(() => {
    let cancelled = false
    const fetchColumns = async () => {
      try {
        const res = await api.get(`/api/db/${schema}/${table}/columns`)
        if (cancelled) return
        const cols = res.data
          .filter((c: any) => !c.is_pk)
          .map((c: any) => c.column_name)
        setColumns(cols)
        if (cols.length > 0) setSelectedColumn(cols[0])
      } catch {
        if (!cancelled) setError('Failed to load columns')
      } finally {
        if (!cancelled) setColumnsLoading(false)
      }
    }
    fetchColumns()
    return () => { cancelled = true }
  }, [schema, table])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!selectedColumn) {
      setError('Select a column to delete')
      return
    }
    if (!confirmed) {
      setError('Please confirm you want to delete this column')
      return
    }
    setLoading(true)
    setError('')
    try {
      await api.patch(`/api/db/tables/${schema}/${table}`, {
        action: 'drop_column',
        column_name: selectedColumn,
      })
      onSuccess()
    } catch (err: any) {
      setError(err?.response?.data?.detail || 'Failed to delete column')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogOverlay onClose={onClose}>
      <form onSubmit={handleSubmit}>
        <h3 className="text-base font-semibold mb-3" style={{ color: 'var(--color-text)' }}>
          Delete Column
        </h3>
        <p className="text-xs mb-3" style={{ color: 'var(--color-text-muted)' }}>
          {schema}.{table}
        </p>

        {columnsLoading ? (
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading columns…</p>
        ) : columns.length === 0 ? (
          <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No deletable columns found.</p>
        ) : (
          <>
            <label className="block text-xs mb-1" style={{ color: 'var(--color-text-muted)' }}>
              Select Column
            </label>
            <select
              value={selectedColumn}
              onChange={e => { setSelectedColumn(e.target.value); setConfirmed(false) }}
              className="w-full px-3 py-2 rounded text-sm mb-3"
              style={{
                backgroundColor: 'var(--color-background)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            >
              {columns.map(col => (
                <option key={col} value={col}>{col}</option>
              ))}
            </select>

            <label className="flex items-center gap-2 text-sm mb-2" style={{ color: 'var(--color-text)' }}>
              <input
                type="checkbox"
                checked={confirmed}
                onChange={e => setConfirmed(e.target.checked)}
              />
              I confirm I want to permanently delete this column and all its data
            </label>
          </>
        )}

        {error && (
          <p className="text-xs mb-2" style={{ color: 'var(--color-error, #ef4444)' }}>{error}</p>
        )}
        <div className="flex justify-end gap-2 mt-3">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm rounded"
            style={{ color: 'var(--color-text-muted)' }}
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading || columns.length === 0 || !confirmed}
            className="px-3 py-1.5 text-sm rounded font-medium"
            style={{
              backgroundColor: 'var(--color-error)',
              color: 'var(--color-on-primary)',
              opacity: (loading || columns.length === 0 || !confirmed) ? 0.6 : 1,
            }}
          >
            {loading ? 'Deleting…' : 'Delete Column'}
          </button>
        </div>
      </form>
    </DialogOverlay>
  )
}
