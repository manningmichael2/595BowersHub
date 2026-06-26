import { Link, useLocation } from 'react-router-dom'
import { useFeatures } from '../hooks/useFeatures'
import { isFeatureVisible } from '../lib/featureNav'

// `feature` ties an item to a registry feature key — shown iff server-permitted
// AND not self-hidden. Items without `feature` always show.
const NAV_ITEMS: { path: string; label: string; icon: string; feature?: string }[] = [
  { path: '/dashboard', label: 'Dashboard', icon: '📊' },
  { path: '/chat', label: 'Chat', icon: '💬' },
  { path: '/finance', label: 'Finance', icon: '💵', feature: 'finance' },
  { path: '/db', label: 'Database', icon: '🗄️', feature: 'database' },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
]

const EXTERNAL_ITEMS = [
  { href: 'http://100.106.180.101:5678', label: 'n8n', icon: '⚡' },
]

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
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        )
      })}

      {/* Separator */}
      <div className="w-px h-5 mx-2" style={{ backgroundColor: 'var(--color-border)' }} />

      {/* External links */}
      {EXTERNAL_ITEMS.map(item => (
        <a
          key={item.href}
          href={item.href}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
          style={{ color: 'var(--color-text-muted)' }}
        >
          <span>{item.icon}</span>
          <span>{item.label}</span>
        </a>
      ))}
    </header>
  )
}
