/**
 * SettingsPage navigator (R12.1) — responsive master-detail. On mobile the
 * section list is full-width and tapping drills into a single pane with a
 * back-to-LIST control (not browser-back, which used to dump to chat). On
 * desktop the sidebar + pane are persistent and default to Profile.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { setMatchMedia } from '../../test/setup'

vi.mock('../../hooks/useFeatures', () => ({ useFeatures: () => null }))
vi.mock('../../stores/auth', () => ({
  useAuthStore: (sel?: (s: unknown) => unknown) => {
    const state = {
      user: { role: 'member', display_name: 'Mike', email: 'mike@example.com' },
      loadFeatureAccess: () => {},
    }
    return sel ? sel(state) : state
  },
}))

import SettingsPage from '../SettingsPage'

const renderPage = () =>
  render(
    <MemoryRouter>
      <SettingsPage />
    </MemoryRouter>,
  )

afterEach(cleanup)

describe('SettingsPage — mobile master-detail', () => {
  it('shows the section list, drills into a pane, and goes back to the list', () => {
    setMatchMedia(false)
    renderPage()

    // List view: title + section buttons, no drill-in back control yet.
    expect(screen.getByRole('heading', { name: 'Settings' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Appearance/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Back to settings list/ })).toBeNull()

    // Drill into Profile → its pane + back-to-list control.
    fireEvent.click(screen.getByRole('button', { name: /Profile/ }))
    expect(screen.getByRole('heading', { name: 'Profile' })).toBeTruthy()
    const back = screen.getByRole('button', { name: /Back to settings list/ })
    expect(back).toBeTruthy()

    // Back returns to the list.
    fireEvent.click(back)
    expect(screen.getByRole('button', { name: /Appearance/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Back to settings list/ })).toBeNull()
  })
})

describe('SettingsPage — desktop sidebar + pane', () => {
  it('shows the sidebar and the Profile pane by default, with no back-to-list control', () => {
    setMatchMedia(true)
    renderPage()
    expect(screen.getByRole('heading', { name: 'Profile' })).toBeTruthy()
    expect(screen.getByRole('button', { name: /Voice/ })).toBeTruthy()
    expect(screen.queryByRole('button', { name: /Back to settings list/ })).toBeNull()
  })
})
