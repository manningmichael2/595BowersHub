import { useLocation, useNavigate } from 'react-router-dom'

const TABS = [
  { path: '/dashboard', label: 'Dashboard', icon: '📊' },
  { path: '/chat', label: 'Chat', icon: '💬' },
  { path: '/finance', label: 'Finance', icon: '💵' },
  { path: '/db', label: 'Database', icon: '🗄️' },
  { path: '/settings', label: 'Settings', icon: '⚙️' },
]

export default function BottomTabBar() {
  const location = useLocation()
  const navigate = useNavigate()

  // Determine active tab
  const activePath = TABS.find(t => location.pathname.startsWith(t.path))?.path
    || (location.pathname === '/' ? '/dashboard' : '/chat')

  return (
    <nav
      className="fixed bottom-0 left-0 right-0 z-50 flex items-center justify-around sm:hidden"
      style={{
        backgroundColor: 'var(--color-surface)',
        borderTop: '1px solid var(--color-border)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
      }}
    >
      {TABS.map(tab => {
        const isActive = activePath === tab.path
        return (
          <button
            key={tab.path}
            onClick={() => navigate(tab.path)}
            className="flex flex-col items-center justify-center py-2 px-4 min-h-[52px] flex-1 transition-colors"
            style={{ color: isActive ? 'var(--color-primary)' : 'var(--color-text-muted)' }}
            aria-current={isActive ? 'page' : undefined}
          >
            <span className="text-lg">{tab.icon}</span>
            <span className="text-[10px] font-medium mt-0.5">{tab.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
