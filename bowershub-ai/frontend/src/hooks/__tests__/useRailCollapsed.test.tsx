/**
 * useRailCollapsed (T11 / R3.2): nav-rail collapse state persists across
 * reload/relaunch via localStorage.
 */
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useRailCollapsed } from '../useRailCollapsed'

beforeEach(() => localStorage.clear())
afterEach(() => localStorage.clear())

describe('useRailCollapsed', () => {
  it('defaults to expanded', () => {
    const { result } = renderHook(() => useRailCollapsed())
    expect(result.current[0]).toBe(false)
  })

  it('persists collapse and rehydrates on a fresh mount (reload/relaunch)', () => {
    const { result, unmount } = renderHook(() => useRailCollapsed())
    act(() => result.current[1](true))
    expect(result.current[0]).toBe(true)
    expect(localStorage.getItem('bh-rail-collapsed')).toBe('1')

    unmount()
    const { result: remounted } = renderHook(() => useRailCollapsed())
    expect(remounted.current[0]).toBe(true)
  })

  it('supports updater functions', () => {
    const { result } = renderHook(() => useRailCollapsed())
    act(() => result.current[1]((c) => !c))
    expect(result.current[0]).toBe(true)
    act(() => result.current[1]((c) => !c))
    expect(result.current[0]).toBe(false)
  })
})
