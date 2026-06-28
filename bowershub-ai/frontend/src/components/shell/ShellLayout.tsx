import { useLayoutEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { useBreakpoint } from '../../hooks/useBreakpoint'
import { useRailCollapsed } from '../../hooks/useRailCollapsed'
import NavRail from './NavRail'
import TopBar from './TopBar'
import BottomTabBar from '../BottomTabBar'

const RAIL_W_EXPANDED = '15rem' // 240px (matches NavRail w-60)
const RAIL_W_COLLAPSED = '4rem' // 64px (matches NavRail w-16)
const TOP_H = '2.75rem' // 44px (matches TopBar / NavRail header h-11)
const BOTTOM_H = 'calc(56px + env(safe-area-inset-bottom, 0px))' // BottomTabBar

/**
 * ShellLayout — the single app-shell frame every authenticated section renders
 * inside via <Outlet/> (R3.1). Chrome is chosen once here by breakpoint (R3.2/
 * R3.3), not per route.
 *
 * Offset consolidation (R3.4): the shell publishes the chrome geometry as CSS
 * vars (--shell-rail-w / --shell-top-h / --shell-bottom-h). Both the section
 * content area (.shell-content, in index.css) and the chat shell (.bh-app-shell)
 * consume them, so individual sections no longer hand-manage `sm:pt-11`/`pb-14`
 * offsets. The vars are reactive to the nav-rail collapse state.
 */
export default function ShellLayout() {
  const { isDesktop } = useBreakpoint()
  const [collapsed, setCollapsed] = useRailCollapsed()

  useLayoutEffect(() => {
    const root = document.documentElement.style
    if (isDesktop) {
      root.setProperty('--shell-rail-w', collapsed ? RAIL_W_COLLAPSED : RAIL_W_EXPANDED)
      root.setProperty('--shell-top-h', TOP_H)
      root.setProperty('--shell-bottom-h', '0px')
    } else {
      root.setProperty('--shell-rail-w', '0px')
      root.setProperty('--shell-top-h', '0px')
      root.setProperty('--shell-bottom-h', BOTTOM_H)
    }
  }, [isDesktop, collapsed])

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
    </>
  )
}
