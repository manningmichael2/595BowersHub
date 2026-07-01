import { Link, useLocation } from 'react-router-dom'
import { PanelLeftClose, PanelLeftOpen, type LucideIcon } from 'lucide-react'
import { useFeatures } from '../../hooks/useFeatures'
import { isNavItemVisible } from '../../lib/featureNav'
import { NAV_ITEMS, TOOL_ITEMS } from '../../lib/navItems'
import { cn } from '../ui/cn'
import { Logo } from '../ui/Logo'

interface NavRailProps {
  collapsed: boolean
  onToggle: () => void
}

function RailLink({
  to,
  label,
  Icon,
  active,
  collapsed,
}: {
  to: string
  label: string
  Icon: LucideIcon
  active: boolean
  collapsed: boolean
}) {
  return (
    <Link
      to={to}
      title={collapsed ? label : undefined}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors duration-fast',
        collapsed && 'justify-center',
        active
          ? 'bg-primary/15 text-primary'
          : 'text-text-muted hover:bg-surface-light hover:text-text',
      )}
    >
      <Icon size={18} strokeWidth={2} aria-hidden className="shrink-0" />
      {!collapsed && <span className="truncate">{label}</span>}
    </Link>
  )
}

/**
 * NavRail — the persistent desktop primary-nav rail (R3.2). Driven by the single
 * `navItems` source, role-filtered (feature gating refined in T13), collapsible
 * to icon-only with the choice persisted. The shell only mounts it ≥ the
 * canonical desktop breakpoint.
 */
export default function NavRail({ collapsed, onToggle }: NavRailProps) {
  const location = useLocation()
  const access = useFeatures()
  const items = NAV_ITEMS.filter((i) => isNavItemVisible(access, i.feature))

  return (
    <nav
      aria-label="Primary"
      className={cn(
        'fixed left-0 top-0 bottom-0 z-shell flex flex-col border-r border-border bg-surface transition-[width] duration-base ease-standard',
        collapsed ? 'w-16' : 'w-60',
      )}
      style={{
        paddingTop: 'env(safe-area-inset-top, 0px)',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        paddingLeft: 'env(safe-area-inset-left, 0px)',
      }}
    >
      <div className={cn('flex h-11 items-center gap-2', collapsed ? 'justify-center px-2' : 'px-4')}>
        <Logo size={24} className="shrink-0" />
        {!collapsed && <span className="text-sm font-semibold text-text">BowersHub</span>}
      </div>

      <div className="flex flex-1 flex-col gap-1 overflow-y-auto px-2 py-2">
        {items.map((item) => (
          <RailLink
            key={item.path}
            to={item.path}
            label={item.label}
            Icon={item.Icon}
            collapsed={collapsed}
            active={
              location.pathname.startsWith(item.path) ||
              (item.path === '/dashboard' && location.pathname === '/')
            }
          />
        ))}
        <div className="my-2 h-px bg-border" />
        {TOOL_ITEMS.map((item) => (
          <RailLink
            key={item.path}
            to={item.path}
            label={item.label}
            Icon={item.Icon}
            collapsed={collapsed}
            active={location.pathname.startsWith(item.path)}
          />
        ))}
      </div>

      <button
        type="button"
        onClick={onToggle}
        aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        className={cn(
          'm-2 flex items-center gap-3 rounded-md px-3 py-2 text-sm text-text-muted transition-colors hover:bg-surface-light hover:text-text',
          collapsed && 'justify-center',
        )}
      >
        {collapsed ? (
          <PanelLeftOpen size={18} aria-hidden />
        ) : (
          <>
            <PanelLeftClose size={18} aria-hidden />
            <span>Collapse</span>
          </>
        )}
      </button>
    </nav>
  )
}
