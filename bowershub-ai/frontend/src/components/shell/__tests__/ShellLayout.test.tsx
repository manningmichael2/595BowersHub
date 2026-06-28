/**
 * ShellLayout (T10 / R3.1): verifies the layout route wraps section content via
 * <Outlet/> and renders the shared chrome once. TopNav/BottomTabBar are mocked
 * to markers so this test targets the layout seam, not their store deps.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'

vi.mock('../../TopNav', () => ({ default: () => <nav data-testid="topnav" /> }))
vi.mock('../../BottomTabBar', () => ({ default: () => <nav data-testid="bottomtab" /> }))

import ShellLayout from '../ShellLayout'

afterEach(cleanup)

describe('ShellLayout', () => {
  it('renders the chrome once and the active section via Outlet', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route element={<ShellLayout />}>
            <Route path="/dashboard" element={<div>Dashboard content</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    expect(screen.getByTestId('topnav')).toBeTruthy()
    expect(screen.getByTestId('bottomtab')).toBeTruthy()
    expect(screen.getByText('Dashboard content')).toBeTruthy()
  })
})
