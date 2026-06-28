/**
 * Global command hotkeys live in the shell (T13 / R3.9), so they work on every
 * section — verified here on a non-chat route. Chrome + overlays are mocked to
 * markers to isolate the hotkey wiring.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { setMatchMedia } from '../../../test/setup'
import { useUIStore } from '../../../stores/ui'

vi.mock('../NavRail', () => ({ default: () => <nav data-testid="navrail" /> }))
vi.mock('../TopBar', () => ({ default: () => <header data-testid="topbar" /> }))
vi.mock('../../BottomTabBar', () => ({ default: () => <nav data-testid="bottomtab" /> }))
vi.mock('../../SearchOverlay', () => ({ default: () => <div data-testid="search-overlay" /> }))
vi.mock('../../QuickCaptureOverlay', () => ({
  default: ({ onClose }: { onClose: () => void }) => (
    <div data-testid="quick-capture" onClick={onClose} />
  ),
}))

import ShellLayout from '../ShellLayout'

function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route element={<ShellLayout />}>
          <Route path="/dashboard" element={<div>page</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(() => {
  cleanup()
  useUIStore.setState({ searchOpen: false })
})

describe('shell global hotkeys (non-chat route)', () => {
  it('Cmd/Ctrl+K opens the search overlay', () => {
    setMatchMedia(true)
    renderShell()
    expect(screen.queryByTestId('search-overlay')).toBeNull()
    fireEvent.keyDown(document.body, { key: 'k', code: 'KeyK', ctrlKey: true })
    expect(useUIStore.getState().searchOpen).toBe(true)
    expect(screen.getByTestId('search-overlay')).toBeTruthy()
  })

  it('Escape closes the search overlay', () => {
    setMatchMedia(true)
    renderShell()
    fireEvent.keyDown(document.body, { key: 'k', code: 'KeyK', metaKey: true })
    expect(useUIStore.getState().searchOpen).toBe(true)
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(useUIStore.getState().searchOpen).toBe(false)
  })

  it('Cmd/Ctrl+Shift+K toggles quick capture (distinct from search)', () => {
    setMatchMedia(true)
    renderShell()
    fireEvent.keyDown(document.body, { key: 'k', code: 'KeyK', ctrlKey: true, shiftKey: true })
    expect(screen.getByTestId('quick-capture')).toBeTruthy()
    expect(useUIStore.getState().searchOpen).toBe(false) // shift variant didn't open search
  })
})
