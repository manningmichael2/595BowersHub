/**
 * useMediaQuery / useIsMobile — the one responsiveness seam for the finance
 * pages whose layout swaps DOM structure (table ↔ stacked cards) and can't be a
 * pure CSS breakpoint. jsdom-safe: with no window.matchMedia (the test env) it
 * falls back to desktop, so component tests render the table path deterministically.
 */
import { useEffect, useState } from 'react'

export function useMediaQuery(query: string): boolean {
  const [matches, setMatches] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return false
    return window.matchMedia(query).matches
  })

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return
    const mql = window.matchMedia(query)
    const handler = () => setMatches(mql.matches)
    handler()
    mql.addEventListener('change', handler)
    return () => mql.removeEventListener('change', handler)
  }, [query])

  return matches
}

/** Tailwind's `sm` breakpoint is 640px; "mobile" is below it. */
export function useIsMobile(): boolean {
  return useMediaQuery('(max-width: 639px)')
}
