/**
 * useBreakpoint (T10 / R3.1, R2.7): one canonical breakpoint, driven from
 * matchMedia. Tests both branches via the setMatchMedia harness.
 */
import { describe, it, expect } from 'vitest'
import { renderHook } from '@testing-library/react'
import { useBreakpoint, BREAKPOINT_DESKTOP } from '../useBreakpoint'
import { setMatchMedia } from '../../test/setup'

describe('useBreakpoint', () => {
  it('uses 640px as the single canonical desktop breakpoint', () => {
    expect(BREAKPOINT_DESKTOP).toBe(640)
  })

  it('reports desktop when the canonical media query matches', () => {
    setMatchMedia(true)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.isDesktop).toBe(true)
    expect(result.current.isMobile).toBe(false)
  })

  it('reports mobile when it does not match', () => {
    setMatchMedia(false)
    const { result } = renderHook(() => useBreakpoint())
    expect(result.current.isDesktop).toBe(false)
    expect(result.current.isMobile).toBe(true)
  })
})
