import { useEffect, useLayoutEffect, useState } from 'react'
import { Outlet } from 'react-router-dom'
import { useBreakpoint } from '../../hooks/useBreakpoint'
import { useRailCollapsed } from '../../hooks/useRailCollapsed'
import { useUIStore } from '../../stores/ui'
import NavRail from './NavRail'
import TopBar from './TopBar'
import BottomTabBar from '../BottomTabBar'
import SearchOverlay from '../SearchOverlay'
import QuickCaptureOverlay from '../QuickCaptureOverlay'

const RAIL_W_EXPANDED = '15rem' // 240px (matches NavRail w-60)
const RAIL_W_COLLAPSED = '4rem' // 64px (matches NavRail w-16)
// Top bar height + the safe-area inset so content clears a notch on installed PWAs.
const TOP_H = 'calc(2.75rem + env(safe-area-inset-top, 0px))'
const MOBILE_TOP_H = 'env(safe-area-inset-top, 0px)'
const BOTTOM_H = 'calc(56px + env(safe-area-inset-bottom, 0px))' // BottomTabBar + home indicator

/** True when a Radix Dialog/AlertDialog is open, so global chords don't fire over a modal (R3.9). */
function isModalOpen(): boolean {
  return !!document.querySelector(
    '[role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]',
  )
}

/**
 * ShellLayout — the single app-shell frame every authenticated section renders
 * inside via <Outlet/> (R3.1). Chrome is chosen once here by breakpoint (R3.2/
 * R3.3); chrome offsets are published as CSS vars (R3.4); global command hotkeys
 * + the search/quick-capture overlays live here so they work on every section
 * (R3.9); safe-area insets keep chrome clear of notches/home indicators (R3.6).
 */
export default function ShellLayout() {
  const { isDesktop } = useBreakpoint()
  const [collapsed, setCollapsed] = useRailCollapsed()
  const searchOpen = useUIStore((s) => s.searchOpen)
  const setSearchOpen = useUIStore((s) => s.setSearchOpen)
  const [quickCaptureOpen, setQuickCaptureOpen] = useState(false)

  // Publish chrome geometry so .shell-content + .bh-app-shell offset uniformly.
  useLayoutEffect(() => {
    const root = document.documentElement.style
    if (isDesktop) {
      root.setProperty('--shell-rail-w', collapsed ? RAIL_W_COLLAPSED : RAIL_W_EXPANDED)
      root.setProperty('--shell-top-h', TOP_H)
      root.setProperty('--shell-bottom-h', '0px')
    } else {
      root.setProperty('--shell-rail-w', '0px')
      root.setProperty('--shell-top-h', MOBILE_TOP_H)
      root.setProperty('--shell-bottom-h', BOTTOM_H)
    }
  }, [isDesktop, collapsed])

  // Global command hotkeys (R3.9): Cmd/Ctrl+K → search, Cmd/Ctrl+Shift+K →
  // quick capture, Escape → close search. `code === 'KeyK'` is layout-robust.
  // Skipped while a Radix modal owns focus so the chords don't fight it.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const isMod = e.ctrlKey || e.metaKey
      const isK = e.code === 'KeyK' || e.key === 'k' || e.key === 'K'
      if (isMod && isK) {
        if (isModalOpen()) return
        e.preventDefault()
        if (e.shiftKey) setQuickCaptureOpen((v) => !v)
        else setSearchOpen(!useUIStore.getState().searchOpen)
        return
      }
      if (e.key === 'Escape' && useUIStore.getState().searchOpen) {
        setSearchOpen(false)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [setSearchOpen])

  return (
    <>
      {isDesktop && (
        <>
          <NavRail collapsed={collapsed} onToggle={() => setCollapsed((c) => !c)} />
          <TopBar />
        </>
      )}

      <div className="shell-content">
        <Outlet />
      </div>

      {!isDesktop && <BottomTabBar />}

      {/* Global overlays — available on every section, not just chat (R3.9). */}
      {searchOpen && <SearchOverlay />}
      {quickCaptureOpen && <QuickCaptureOverlay onClose={() => setQuickCaptureOpen(false)} />}
    </>
  )
}
