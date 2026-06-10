/**
 * useUndoRedo — hook that provides undo/redo capabilities for the DB browser.
 *
 * Exposes:
 *   - undo(): Undo the last operation for the current session
 *   - redo(): Redo the last undone operation
 *   - canUndo: Whether there are operations available to undo
 *   - canRedo: Whether there are operations available to redo
 *   - sessionId: The current session UUID (used in X-DB-Session-Id header)
 *
 * This hook reads from the Zustand db-browser store and delegates undo/redo
 * calls through the store actions (which hit the backend with the session header).
 *
 * _Requirements: 29.1, 29.2, 29.3, 29.4, 29.5, 29.6, 29.7_
 */
import { useDbBrowserStore } from '../stores/db-browser'

export interface UndoRedoState {
  undo: () => Promise<void>
  redo: () => Promise<void>
  canUndo: boolean
  canRedo: boolean
  sessionId: string | null
}

export function useUndoRedo(): UndoRedoState {
  const undo = useDbBrowserStore(s => s.undo)
  const redo = useDbBrowserStore(s => s.redo)
  const undoStack = useDbBrowserStore(s => s.undoStack)
  const redoStack = useDbBrowserStore(s => s.redoStack)
  const sessionId = useDbBrowserStore(s => s.sessionId)

  return {
    undo,
    redo,
    canUndo: undoStack.length > 0,
    canRedo: redoStack.length > 0,
    sessionId,
  }
}

export default useUndoRedo
