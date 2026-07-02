import { NavLink } from 'react-router-dom'
import { LogOut, X, type LucideIcon } from 'lucide-react'
import { Sheet, SheetContent, SheetClose, SheetTitle } from '../ui'
import { useFeatures } from '../../hooks/useFeatures'
import { isNavItemVisible } from '../../lib/featureNav'
import { NAV_ITEMS, TOOL_ITEMS } from '../../lib/navItems'
import { useAuthStore } from '../../stores/auth'
import { cn } from '../ui/cn'
import { Logo } from '../ui/Logo'

interface NavDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

function DrawerLink({
  to,
  label,
  Icon,
  onNavigate,
}: {
  to: string
  label: string
  Icon: LucideIcon
  onNavigate: () => void
}) {
  return (
    <NavLink
      to={to}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors duration-fast',
          isActive
            ? 'bg-primary/15 text-primary'
            : 'text-text-muted hover:bg-surface-light hover:text-text',
        )
      }
    >
      <Icon size={20} strokeWidth={2} aria-hidden className="shrink-0" />
      <span className="truncate">{label}</span>
    </NavLink>
  )
}

/**
 * NavDrawer — the mobile primary-nav surface (R3.2/R3.3). The bottom tab bar
 * shows the top destinations; this scrollable drawer carries ALL of them
 * (including feature-gated Finance/Database, rendered optimistically so a slow/
 * unreachable features call can't strand them), the embedded tools, and the
 * account/logout that mobile otherwise had nowhere to put. Built on the Sheet
 * primitive, so it inherits focus-trap/ESC/scroll-lock and offsets safe areas.
 */
export default function NavDrawer({ open, onOpenChange }: NavDrawerProps) {
  const access = useFeatures()
  const user = useAuthStore((s) => s.user)
  const logout = useAuthStore((s) => s.logout)
  const items = NAV_ITEMS.filter((i) => isNavItemVisible(access, i.feature))
  const close = () => onOpenChange(false)

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" aria-describedby={undefined}>
        <SheetTitle>Navigation</SheetTitle>

        <div className="flex h-11 shrink-0 items-center justify-between px-4">
          <div className="flex items-center gap-2">
            <Logo size={22} className="shrink-0" />
            <span className="text-sm font-semibold text-text">BowersHub</span>
          </div>
          <SheetClose
            aria-label="Close navigation"
            className="rounded-md p-1 text-text-muted transition-colors hover:bg-surface-light hover:text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          >
            <X size={18} aria-hidden />
          </SheetClose>
        </div>

        <nav aria-label="Primary" className="flex flex-1 flex-col gap-1 overflow-y-auto px-2 py-2">
          {items.map((item) => (
            <DrawerLink key={item.path} to={item.path} label={item.label} Icon={item.Icon} onNavigate={close} />
          ))}
          {TOOL_ITEMS.length > 0 && <div className="my-2 h-px bg-border" />}
          {TOOL_ITEMS.map((item) => (
            <DrawerLink key={item.path} to={item.path} label={item.label} Icon={item.Icon} onNavigate={close} />
          ))}
        </nav>

        <div className="mt-auto shrink-0 border-t border-border p-3">
          <div className="flex items-center gap-3 px-1 py-2">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-on-primary">
              {user?.display_name?.[0]?.toUpperCase() || '?'}
            </span>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm font-medium text-text">{user?.display_name}</div>
              <div className="truncate text-xs text-text-muted">{user?.email}</div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => {
              close()
              logout()
            }}
            className="mt-1 flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium text-text-muted transition-colors hover:bg-surface-light hover:text-text"
          >
            <LogOut size={20} strokeWidth={2} aria-hidden className="shrink-0" />
            Log out
          </button>
        </div>
      </SheetContent>
    </Sheet>
  )
}
