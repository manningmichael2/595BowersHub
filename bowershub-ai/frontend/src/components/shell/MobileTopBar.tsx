import { Menu, Search } from 'lucide-react'
import { useUIStore } from '../../stores/ui'
import { Logo } from '../ui/Logo'

interface MobileTopBarProps {
  onMenuClick: () => void
}

/**
 * MobileTopBar — the persistent top chrome on mobile (R3.2). Desktop gets the
 * NavRail + contextual TopBar; before this, mobile had ONLY the bottom tab bar,
 * so any page outside the five tabs had no title, no account/logout, and no way
 * back except browser-back (which unwound to chat). This bar carries the menu
 * (opens NavDrawer for full navigation, incl. gated sections), the brand, and a
 * global-search entry; the drawer owns account/logout. Height + safe-area inset
 * are mirrored into --shell-top-h by ShellLayout so content offsets below it.
 */
export default function MobileTopBar({ onMenuClick }: MobileTopBarProps) {
  const setSearchOpen = useUIStore((s) => s.setSearchOpen)

  return (
    <header
      className="fixed left-0 right-0 top-0 z-shell flex items-center justify-between gap-2 border-b border-border bg-surface"
      style={{
        height: 'calc(2.75rem + env(safe-area-inset-top, 0px))',
        paddingTop: 'env(safe-area-inset-top, 0px)',
        paddingLeft: 'calc(0.5rem + env(safe-area-inset-left, 0px))',
        paddingRight: 'calc(0.5rem + env(safe-area-inset-right, 0px))',
      }}
    >
      <div className="flex items-center gap-1.5">
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open navigation"
          className="rounded-md p-2 text-text-muted transition-colors hover:bg-surface-light hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <Menu size={20} aria-hidden />
        </button>
        <Logo size={22} className="shrink-0" />
        <span className="text-sm font-semibold text-text">BowersHub</span>
      </div>

      <button
        type="button"
        onClick={() => setSearchOpen(true)}
        aria-label="Search"
        className="rounded-md p-2 text-text-muted transition-colors hover:bg-surface-light hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
      >
        <Search size={18} aria-hidden />
      </button>
    </header>
  )
}
