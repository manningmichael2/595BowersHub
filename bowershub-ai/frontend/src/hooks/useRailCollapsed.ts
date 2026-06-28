import { useCallback, useState } from 'react'

const STORAGE_KEY = 'bh-rail-collapsed'

type Updater = boolean | ((prev: boolean) => boolean)

/**
 * Persisted collapse state for the desktop nav rail (R3.2). Mirrors the
 * theme-persistence pattern (localStorage) so the choice survives reload and
 * PWA relaunch. Fails open (expanded) if storage is unavailable.
 */
export function useRailCollapsed(): [boolean, (updater: Updater) => void] {
  const [collapsed, setState] = useState<boolean>(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) === '1'
    } catch {
      return false
    }
  })

  const setCollapsed = useCallback((updater: Updater) => {
    setState((prev) => {
      const next = typeof updater === 'function' ? updater(prev) : updater
      try {
        localStorage.setItem(STORAGE_KEY, next ? '1' : '0')
      } catch {
        /* ignore */
      }
      return next
    })
  }, [])

  return [collapsed, setCollapsed]
}
