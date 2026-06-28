import { Outlet } from 'react-router-dom'
import TopNav from '../TopNav'
import BottomTabBar from '../BottomTabBar'

/**
 * ShellLayout — the single app-shell frame every authenticated section renders
 * inside via <Outlet/> (R3.1). This is the structural seam: the app's chrome is
 * chosen *here*, once, instead of each section assembling its own.
 *
 * T10 is a behaviour-preserving refactor — it wraps the existing
 * TopNav/BottomTabBar around the Outlet so the route tree becomes a layout
 * route without changing what renders. The desktop nav rail + contextual top
 * bar, the mobile secondary nav, and the offset consolidation (R3.2–R3.4) build
 * on this in T11–T13.
 */
export default function ShellLayout() {
  return (
    <>
      <TopNav />
      <Outlet />
      <BottomTabBar />
    </>
  )
}
