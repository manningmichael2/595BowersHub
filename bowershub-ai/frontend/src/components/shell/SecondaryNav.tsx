import { NavLink } from 'react-router-dom'
import { cn } from '../ui/cn'

export interface SecondaryNavItem {
  to: string
  label: string
  /** Match only the exact path (passed to NavLink `end`). */
  end?: boolean
}

export interface SecondaryNavProps {
  items: SecondaryNavItem[]
  /** Accessible label for the nav landmark (e.g. "Finance"). */
  label: string
  className?: string
}

/**
 * SecondaryNav — the shared in-section navigation primitive (R3.3): one
 * consistent, horizontally-scrollable segmented control that sections render
 * instead of each inventing its own sub-nav row. Works at every width (scrolls
 * on narrow viewports, so the mobile secondary-nav story is the same component).
 */
export function SecondaryNav({ items, label, className }: SecondaryNavProps) {
  return (
    <nav
      aria-label={label}
      className={cn(
        'flex shrink-0 items-center gap-1 overflow-x-auto whitespace-nowrap border-b border-border px-3 py-2',
        className,
      )}
    >
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn(
              'shrink-0 rounded-md px-3 py-1.5 text-xs font-medium transition-colors duration-fast',
              isActive
                ? 'bg-surface-light text-primary'
                : 'text-text-muted hover:text-text',
            )
          }
        >
          {item.label}
        </NavLink>
      ))}
    </nav>
  )
}
