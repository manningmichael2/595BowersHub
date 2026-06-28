/**
 * ShellLayout (T10/T11 / R3.1–R3.4): the layout route renders section content
 * via <Outlet/> and chooses chrome by breakpoint — desktop nav rail + top bar,
 * mobile bottom tab bar. Chrome children are mocked to markers so this targets
 * the shell composition, not their store deps.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { setMatchMedia } from '../../../test/setup'

vi.mock('../NavRail', () => ({ default: () => <nav data-testid="navrail" /> }))
vi.mock('../TopBar', () => ({ default: () => <header data-testid="topbar" /> }))
vi.mock('../MobileTopBar', () => ({ default: () => <header data-testid="mobiletopbar" /> }))
vi.mock('../NavDrawer', () => ({ default: () => <div data-testid="navdrawer" /> }))
vi.mock('../../BottomTabBar', () => ({ default: () => <nav data-testid="bottomtab" /> }))

import ShellLayout from '../ShellLayout'

function renderShell() {
  return render(
    <MemoryRouter initialEntries={['/dashboard']}>
      <Routes>
        <Route element={<ShellLayout />}>
          <Route path="/dashboard" element={<div>Dashboard content</div>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

afterEach(cleanup)

describe('ShellLayout', () => {
  it('desktop: renders nav rail + top bar (not the mobile chrome) around the Outlet', () => {
    setMatchMedia(true)
    renderShell()
    expect(screen.getByTestId('navrail')).toBeTruthy()
    expect(screen.getByTestId('topbar')).toBeTruthy()
    expect(screen.queryByTestId('bottomtab')).toBeNull()
    expect(screen.queryByTestId('mobiletopbar')).toBeNull()
    expect(screen.queryByTestId('navdrawer')).toBeNull()
    expect(screen.getByText('Dashboard content')).toBeTruthy()
  })

  it('mobile: renders the mobile top bar + drawer + bottom tab bar (not the rail/desktop top bar)', () => {
    setMatchMedia(false)
    renderShell()
    expect(screen.getByTestId('mobiletopbar')).toBeTruthy()
    expect(screen.getByTestId('navdrawer')).toBeTruthy()
    expect(screen.getByTestId('bottomtab')).toBeTruthy()
    expect(screen.queryByTestId('navrail')).toBeNull()
    expect(screen.queryByTestId('topbar')).toBeNull()
    expect(screen.getByText('Dashboard content')).toBeTruthy()
  })

  it('desktop: publishes the shell offset CSS vars', () => {
    setMatchMedia(true)
    renderShell()
    const root = document.documentElement.style
    expect(root.getPropertyValue('--shell-top-h')).toContain('2.75rem') // + safe-area inset
    expect(root.getPropertyValue('--shell-rail-w')).not.toBe('0px')
  })

  it('mobile: publishes a real top-bar height (content clears the mobile top bar)', () => {
    setMatchMedia(false)
    renderShell()
    const root = document.documentElement.style
    expect(root.getPropertyValue('--shell-top-h')).toContain('2.75rem')
    expect(root.getPropertyValue('--shell-rail-w')).toBe('0px')
    expect(root.getPropertyValue('--shell-bottom-h')).toContain('56px')
  })
})
