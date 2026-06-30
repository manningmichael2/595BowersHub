/**
 * UndoRedoProvider — manages session-scoped undo/redo for the DB browser.
 *
 * Responsibilities:
 * - Generates a session UUID (crypto.randomUUID()) on mount and stores it in
 *   the Zustand db-browser store
 * - Listens for Ctrl+Z (undo) and Ctrl+Shift+Z (redo) keyboard shortcuts
 * - Clears the session (calls POST /api/db/undo/clear-session) and resets
 *   the sessionId when the user navigates away from /db routes
 *
 * Usage: wrap the DbBrowserPage content with this provider so that undo/redo
 * is active for the entire DB browser session.
 *
 * _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7_
 */
import { useEffect, useCallback, useRef, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { useDbBrowserStore } from '../../stores/db-browser'
import { api } from '../../services/api'

export interface UndoRedoProviderProps {
  children: ReactNode
}

/**
 * Sends the clear-session request to the backend. Routed through the api client
 * so it inherits auth-token injection + 401 refresh; the X-DB-Session-Id header
 * goes via the client's extra-headers arg.
 */
async function clearSession(sessionId: string): Promise<void> {
  try {
    await api.post('/api/db/undo/clear-session', undefined, { 'X-DB-Session-Id': sessionId })
  } catch {
    // Best-effort cleanup — if it fails, server-side TTL will handle it
  }
}

export default function UndoRedoProvider({ children }: UndoRedoProviderProps) {
  const location = useLocation()
  const sessionIdRef = useRef<string | null>(null)

  const undo = useDbBrowserStore(s => s.undo)
  const redo = useDbBrowserStore(s => s.redo)
  const undoStack = useDbBrowserStore(s => s.undoStack)
  const redoStack = useDbBrowserStore(s => s.redoStack)

  // Generate session UUID on mount and store it in Zustand
  useEffect(() => {
    const newSessionId = crypto.randomUUID()
    sessionIdRef.current = newSessionId
    useDbBrowserStore.setState({ sessionId: newSessionId })

    // Cleanup: clear session on unmount (component unmounts when navigating away from /db)
    return () => {
      if (sessionIdRef.current) {
        clearSession(sessionIdRef.current)
        useDbBrowserStore.setState({
          sessionId: null,
          undoStack: [],
          redoStack: [],
        })
        sessionIdRef.current = null
      }
    }
  }, [])

  // Watch for navigation away from /db routes and clear session
  const wasOnDbRoute = useRef(true)
  useEffect(() => {
    const isOnDbRoute = location.pathname.startsWith('/db')

    if (wasOnDbRoute.current && !isOnDbRoute && sessionIdRef.current) {
      // User navigated away from /db
      clearSession(sessionIdRef.current)
      useDbBrowserStore.setState({
        sessionId: null,
        undoStack: [],
        redoStack: [],
      })
      sessionIdRef.current = null
    }

    wasOnDbRoute.current = isOnDbRoute
  }, [location.pathname])

  // Keyboard shortcut listener for Ctrl+Z (undo) and Ctrl+Shift+Z (redo)
  const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // Only intercept when on a /db route with an active session
    if (!sessionIdRef.current) return

    // Don't intercept if the user is typing in a form element
    // (unless it's our Ctrl shortcut)
    const target = e.target as HTMLElement
    const isFormElement =
      target.tagName === 'INPUT' ||
      target.tagName === 'TEXTAREA' ||
      target.tagName === 'SELECT' ||
      target.isContentEditable

    // Only handle Ctrl/Meta+Z combinations
    if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== 'z') return

    // Don't intercept native undo/redo in form elements that haven't been
    // committed yet (let the browser handle text editing undo)
    if (isFormElement) {
      // Check if the db-browser is currently in inline-editing mode
      const { editingCell } = useDbBrowserStore.getState()
      if (editingCell) return // Let the inline editor handle its own undo
    }

    e.preventDefault()

    if (e.shiftKey) {
      // Ctrl+Shift+Z → Redo
      const { redoStack } = useDbBrowserStore.getState()
      if (redoStack.length > 0) {
        redo()
      }
    } else {
      // Ctrl+Z → Undo
      const { undoStack } = useDbBrowserStore.getState()
      if (undoStack.length > 0) {
        undo()
      }
    }
  }, [undo, redo])

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  return <>{children}</>
}
