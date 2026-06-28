import { useLocation, useNavigate } from 'react-router-dom'
import { useFeatures } from '../hooks/useFeatures'
import { isNavItemVisible } from '../lib/featureNav'
import { NAV_ITEMS } from '../lib/navItems'

export default function BottomTabBar() {
  const location = useLocation()
  const navigate = useNavigate()
  const access = useFeatures()
  const tabs = NAV_ITEMS.filter(t => isNavItemVisible(access, t.feature))

  // Determine active tab
  const activePath = tabs.find(t => location.pathname.startsWith(t.path))?.path
    || (location.pathname === '/' ? '/dashboard' : '/chat')

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-shell flex items-center justify-around sm:hidden"
      style={{
        backgroundColor: 'var(--color-surface)',
        borderTop: '1px solid var(--color-border)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        paddingLeft: 'env(safe-area-inset-left, 0px)',
        paddingRight: 'env(safe-area-inset-right, 0px)',
      }}
    >
      {tabs.map(tab => {
        const isActive = activePath === tab.path
        const Icon = tab.Icon
        return (
          <button
            key={tab.path}
            onClick={() => navigate(tab.path)}
            className="flex flex-col items-center justify-center py-2 px-4 min-h-[56px] flex-1 transition-colors"
            style={{ color: isActive ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
            aria-current={isActive ? 'page' : undefined}
          >
            <Icon size={22} strokeWidth={isActive ? 2.4 : 2} aria-hidden />
            <span className="text-[11px] font-medium mt-1">{tab.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
