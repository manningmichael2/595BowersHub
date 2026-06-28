/**
 * DbBrowserPage — top-level layout component for the Native DB Browser.
 *
 * Renders a flex layout with the SchemaSidebar on the left (fixed width)
 * and the main content area on the right using React Router's Routes/Outlet
 * for nested route rendering.
 *
 * On mount, loads schemas and field hints from the store so child components
 * have the data they need immediately.
 *
 * Routes handled:
 *   /db               → WelcomeState (no table selected)
 *   /db/:schema/:table → TableView
 *   /db/:schema/:table/:id → DetailView
 */

import { useEffect, useState } from 'react'
import { Routes, Route } from 'react-router-dom'
import { useDbBrowserStore } from '../stores/db-browser'
import SchemaSidebar from '../components/db-browser/SchemaSidebar'
import TableView from '../components/db-browser/TableView'
import DetailView from '../components/db-browser/DetailView'
import FieldSettingsPage from '../components/db-browser/FieldSettingsPage'
import InboxProcessor from '../components/db-browser/InboxProcessor'
import UndoRedoProvider from '../components/db-browser/UndoRedoProvider'

/**
 * Welcome state shown at /db when no table is selected.
 * Will be replaced by WelcomeState.tsx in task 4.3.
 */
function WelcomePlaceholder() {
  const schemas = useDbBrowserStore(s => s.schemas)
  const tableCount = schemas.reduce((sum, s) => sum + s.tables.length, 0)

  return (
    <div
      className="flex items-center justify-center h-full"
      style={{ color: 'var(--color-text-muted)' }}
    >
      <div className="text-center">
        <h1 className="text-xl font-semibold mb-2" style={{ color: 'var(--color-text)' }}>
          Database Browser
        </h1>
        <p className="mb-1">
          {schemas.length} schema{schemas.length !== 1 ? 's' : ''}, {tableCount} table{tableCount !== 1 ? 's' : ''}
        </p>
        <p>Select a table from the sidebar to get started.</p>
      </div>
    </div>
  )
}

export default function DbBrowserPage() {
  const loadSchemas = useDbBrowserStore(s => s.loadSchemas)
  const loadFieldHints = useDbBrowserStore(s => s.loadFieldHints)
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Load schemas and field hints on mount
  useEffect(() => {
    loadSchemas()
    loadFieldHints()
  }, [loadSchemas, loadFieldHints])

  return (
    <UndoRedoProvider>
      <div
        className="flex h-full overflow-hidden"
        style={{ backgroundColor: 'var(--color-background)' }}
      >
        {/* Schema Sidebar — fixed width on desktop, overlay drawer on mobile */}
        <SchemaSidebar
          mobileOpen={sidebarOpen}
          onMobileClose={() => setSidebarOpen(false)}
        />

        {/* Main content area — nested routes render here */}
        <main
          className="flex-1 min-w-0 overflow-y-auto flex flex-col"
          style={{ backgroundColor: 'var(--color-surface)' }}
        >
          {/* Mobile header with hamburger toggle — visible only at < 640px */}
          <div
            className="sm:hidden shrink-0 flex items-center px-3 py-2"
            style={{ borderBottom: '1px solid var(--color-border)' }}
          >
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="p-2.5 rounded transition-colors min-w-[44px] min-h-[44px] flex items-center justify-center"
              style={{ color: 'var(--color-text)' }}
              aria-label="Open schema sidebar"
            >
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                <line x1="3" y1="6" x2="21" y2="6" />
                <line x1="3" y1="12" x2="21" y2="12" />
                <line x1="3" y1="18" x2="21" y2="18" />
              </svg>
            </button>
            <span
              className="ml-2 text-sm font-medium"
              style={{ color: 'var(--color-text)' }}
            >
              Database Browser
            </span>
          </div>

          {/* Route content */}
          <div className="flex-1 min-h-0">
            <Routes>
              <Route index element={<WelcomePlaceholder />} />
              <Route path="settings" element={<FieldSettingsPage />} />
              <Route path="inbox" element={<InboxProcessor />} />
              <Route path=":schema/:table" element={<TableView />} />
              <Route path=":schema/:table/:id" element={<DetailView />} />
            </Routes>
          </div>
        </main>
      </div>
    </UndoRedoProvider>
  )
}
