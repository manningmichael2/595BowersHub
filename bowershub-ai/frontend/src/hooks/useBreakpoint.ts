import { useEffect, useState } from 'react'

/**
 * The single canonical breakpoint (px) that governs the desktop↔mobile chrome
 * switch for the whole app shell (R3.1). Before this, primary nav switched at
 * Tailwind `sm` (640) while the chat sidebar switched at `md` (768), leaving an
 * undefined 640–767px band ("desktop nav + mobile chat sidebar"). Everything is
 * unified on `sm` (640): the chat sidebar is re-pointed to match (a reviewed
 * behavior change), so e.g. a 700px window is coherently "desktop" everywhere.
 *
 * Keep this aligned with the Tailwind `sm:` utilities used by the chrome.
 */
export const BREAKPOINT_DESKTOP = 640
export const DESKTOP_MEDIA_QUERY = `(min-width: ${BREAKPOINT_DESKTOP}px)`

export interface Breakpoint {
  isDesktop: boolean
  isMobile: boolean
}

/**
 * Reactive viewport hook the shell uses to choose its chrome by breakpoint (not
 * per route). Subscribes to the canonical media query so the shell re-renders on
 * resize / orientation change. Tests drive both branches via `setMatchMedia`.
 */
export function useBreakpoint(): Breakpoint {
  const [isDesktop, setIsDesktop] = useState<boolean>(() =>
    typeof window !== 'undefined' && typeof window.matchMedia === 'function'
      ? window.matchMedia(DESKTOP_MEDIA_QUERY).matches
      : true,
  )

  useEffect(() => {
    const mql = window.matchMedia(DESKTOP_MEDIA_QUERY)
    const onChange = () => setIsDesktop(mql.matches)
    onChange()
    mql.addEventListener('change', onChange)
    return () => mql.removeEventListener('change', onChange)
  }, [])

  return { isDesktop, isMobile: !isDesktop }
}
