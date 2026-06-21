/**
 * FinanceLayout — the single Finance hub. One nav entry (/finance) with sub-tabs
 * for every finance tool. Provides the shared scroll container + top offset
 * (sm:pt-11 clears the fixed TopNav — fixes the cut-off that the standalone
 * finance pages had), so each tool just renders its content via <Outlet>.
 */
import { NavLink, Outlet } from 'react-router-dom'

const TABS = [
  { to: '/finance/transactions', label: 'Transactions' },
  { to: '/finance/budgets', label: 'Budgets' },
  { to: '/finance/net-worth', label: 'Net Worth' },
  { to: '/finance/recurring', label: 'Recurring' },
]

export default function FinanceLayout() {
  return (
    <div
      className="flex flex-col h-full overflow-y-auto overflow-x-hidden pb-14 sm:pb-0 sm:pt-11"
      style={{ backgroundColor: 'var(--color-background)' }}
    >
      <div className="flex items-center gap-1 px-4 py-2 shrink-0" style={{ borderBottom: '1px solid var(--color-border)' }}>
        <span className="text-sm font-semibold mr-3" style={{ color: 'var(--color-text)' }}>Finance</span>
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className="px-3 py-1.5 rounded-md text-xs font-medium transition-colors"
            style={({ isActive }) => ({
              backgroundColor: isActive ? 'color-mix(in srgb, var(--color-primary) 20%, transparent)' : 'transparent',
              color: isActive ? 'var(--color-primary)' : 'var(--color-text-muted)',
            })}
          >
            {t.label}
          </NavLink>
        ))}
      </div>
      <div className="flex-1 min-h-0">
        <Outlet />
      </div>
    </div>
  )
}
