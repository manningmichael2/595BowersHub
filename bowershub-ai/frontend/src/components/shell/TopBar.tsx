import { useLocation } from 'react-router-dom'
import { LogOut, Search } from 'lucide-react'
import { useAuthStore } from '../../stores/auth'
import { useUIStore } from '../../stores/ui'
import { NAV_ITEMS, TOOL_ITEMS } from '../../lib/navItems'
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from '../ui'

function usePageTitle(): string {
  const { pathname } = useLocation()
  const item =
    [...NAV_ITEMS, ...TOOL_ITEMS].find((i) => pathname.startsWith(i.path)) ??
    (pathname === '/' ? NAV_ITEMS[0] : undefined)
  return item?.label ?? ''
}

/**
 * TopBar — the contextual desktop top bar (R3.2): page title (left) + account
 * menu (right). Positioned right of the nav rail via the shared --shell-rail-w
 * var. Global search entry + page-action slot land in T13 / P4.
 */
export default function TopBar() {
  const title = usePageTitle()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const setSearchOpen = useUIStore((s) => s.setSearchOpen)

  return (
    <header
      className="fixed right-0 top-0 z-shell flex items-center justify-between gap-3 border-b border-border bg-surface px-4"
      style={{
        left: 'var(--shell-rail-w, 0px)',
        height: 'calc(2.75rem + env(safe-area-inset-top, 0px))',
        paddingTop: 'env(safe-area-inset-top, 0px)',
        paddingRight: 'calc(1rem + env(safe-area-inset-right, 0px))',
      }}
    >
      <h1 className="truncate text-sm font-semibold text-text">{title}</h1>

      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={() => setSearchOpen(true)}
          aria-label="Search"
          title="Search (⌘K)"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-text-muted transition-colors hover:bg-surface-light hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        >
          <Search size={16} aria-hidden />
        </button>

        <DropdownMenu>
        <DropdownMenuTrigger className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm text-text-muted transition-colors hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary">
          <span className="flex h-7 w-7 items-center justify-center rounded-full bg-primary text-xs font-semibold text-on-primary">
            {user?.display_name?.[0]?.toUpperCase() || '?'}
          </span>
          <span className="max-w-[12rem] truncate">{user?.display_name}</span>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuLabel className="max-w-[16rem] truncate">{user?.email}</DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem onSelect={() => logout()}>
            <LogOut className="h-4 w-4" aria-hidden />
            Log out
          </DropdownMenuItem>
        </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  )
}
