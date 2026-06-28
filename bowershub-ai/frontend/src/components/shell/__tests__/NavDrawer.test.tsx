/**
 * NavDrawer (R3.2/R3.3) — the mobile full-nav drawer. Verifies it surfaces ALL
 * primary destinations including the feature-gated ones OPTIMISTICALLY while
 * access is unresolved (the fix for Finance/Database vanishing when
 * /api/me/features is unreachable), and that account logout is reachable —
 * mobile previously had nowhere to log out.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('../../../hooks/useFeatures', () => ({ useFeatures: () => null }))
const logout = vi.fn()
vi.mock('../../../stores/auth', () => ({
  useAuthStore: (sel: (s: unknown) => unknown) =>
    sel({ user: { display_name: 'Mike', email: 'mike@example.com' }, logout }),
}))

import NavDrawer from '../NavDrawer'

afterEach(cleanup)

describe('NavDrawer', () => {
  it('shows every primary destination (incl. gated Finance/Database) + logout while access is null', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <NavDrawer open onOpenChange={() => {}} />
      </MemoryRouter>,
    )
    for (const label of ['Dashboard', 'Chat', 'Finance', 'Database', 'Settings']) {
      expect(screen.getByRole('link', { name: label })).toBeTruthy()
    }
    expect(screen.getByRole('button', { name: /log out/i })).toBeTruthy()
    expect(screen.getByText('mike@example.com')).toBeTruthy()
  })
})
