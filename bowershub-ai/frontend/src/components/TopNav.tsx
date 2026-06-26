import { Link, useLocation } from 'react-router-dom'
import { useFeatures } from '../hooks/useFeatures'
import { isFeatureVisible } from '../lib/featureNav'
import { NAV_ITEMS, TOOL_ITEMS } from '../lib/navItems'

export default function TopNav() {
  const location = useLocation()
  const access = useFeatures()
  const items = NAV_ITEMS.filter(i => !i.feature || isFeatureVisible(access, i.feature))

  return (
    <header
      className="hidden sm:flex items-center gap-1 px-4 h-11 shrink-0 z-40 fixed top-0 left-0 right-0"
      style={{ backgroundColor: 'var(--color-surface)', borderBottom: '1px solid var(--color-border)' }}
    >
      {/* App name */}
      <span className="text-sm font-semibold mr-4" style={{ color: 'var(--color-text)' }}>BowersHub</span>

      {/* Internal nav */}
      {items.map(item => {
        const isActive = location.pathname.startsWith(item.path) || (item.path === '/dashboard' && location.pathname === '/')
        const Icon = item.Icon
        return (
          <Link
            key={item.path}
            to={item.path}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
            style={{
              backgroundColor: isActive ? 'color-mix(in srgb, var(--color-primary) 20%, transparent)' : 'transparent',
              color: isActive ? 'var(--color-primary)' : 'var(--color-text-muted)',
            }}
          >
            <Icon size={15} strokeWidth={2} aria-hidden />
            <span>{item.label}</span>
          </Link>
        )
      })}

      {/* Separator */}
      <div className="w-px h-5 mx-2" style={{ backgroundColor: 'var(--color-border)' }} />

      {/* Embedded tools (in-app iframe shell — no external host:port) */}
      {TOOL_ITEMS.map(item => {
        const Icon = item.Icon
        return (
          <Link
            key={item.path}
            to={item.path}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
            style={{ color: 'var(--color-text-muted)' }}
          >
            <Icon size={15} strokeWidth={2} aria-hidden />
            <span>{item.label}</span>
          </Link>
        )
      })}
    </header>
  )
}
