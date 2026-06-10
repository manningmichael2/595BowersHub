/**
 * KeyboardNavigationProvider — thin wrapper that enables keyboard grid
 * navigation within the DB browser TableView.
 *
 * Responsibilities:
 * - Calls the `useKeyboardNavigation` hook to handle keydown events
 * - Provides visual focus styling via a `data-focused-cell` attribute
 *   and CSS custom properties for the focus ring color
 * - Passes navigation callbacks (create, duplicate, delete, search focus)
 *   down to the hook
 *
 * Usage: wrap the table area in TableView with this provider and pass the
 * required callbacks. The focused cell receives an outline via CSS:
 *   td[data-kb-focused="true"] { outline: 2px solid var(--color-kb-focus-ring) }
 *
 * _Requirements: 26.1, 26.2, 26.3, 26.4, 26.5, 26.6, 26.7_
 */
import type { ReactNode, RefObject } from 'react'
import { useKeyboardNavigation } from '../../hooks/useKeyboardNavigation'

export interface KeyboardNavigationProviderProps {
  children: ReactNode
  /** Called when Ctrl+N triggers row creation */
  onCreateRow?: () => void
  /** Called when Ctrl+D triggers row duplication */
  onDuplicateRow?: (rowIndex: number) => void
  /** Called when Delete triggers row deletion confirmation */
  onDeleteRow?: (rowIndex: number) => void
  /** Ref to the search input for Ctrl+F focus */
  searchInputRef?: RefObject<HTMLInputElement | null>
}

/**
 * CSS class injected as a `<style>` block for the keyboard focus ring.
 * Uses CSS custom properties for theme reactivity.
 */
const FOCUS_RING_STYLES = `
  td[data-kb-focused="true"] {
    outline: 2px solid var(--color-kb-focus-ring, var(--color-primary, #6366f1));
    outline-offset: -2px;
    position: relative;
    z-index: 1;
  }
`

export default function KeyboardNavigationProvider({
  children,
  onCreateRow,
  onDuplicateRow,
  onDeleteRow,
  searchInputRef,
}: KeyboardNavigationProviderProps) {
  // Attach the keyboard event listener via the hook
  useKeyboardNavigation({
    onCreateRow,
    onDuplicateRow,
    onDeleteRow,
    searchInputRef,
  })

  return (
    <>
      {/* Inject focus ring styles (SSR-safe since this is a client-only SPA) */}
      <style>{FOCUS_RING_STYLES}</style>
      {children}
    </>
  )
}
