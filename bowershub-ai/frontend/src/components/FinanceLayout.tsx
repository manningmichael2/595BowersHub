/**
 * FinanceLayout — the single Finance hub. One nav entry (/finance) with sub-tabs
 * for every finance tool. Provides the shared scroll container; chrome offsets
 * are owned by the app shell (R3.4), so each tool just renders via <Outlet>.
 */
import { NavLink, Outlet } from 'react-router-dom'

const TABS = [
  { to: '/finance/transactions', label: 'Transactions' },
  { to: '/finance/ask', label: 'Ask' },
  { to: '/finance/insights', label: 'Insights' },
  { to: '/finance/budgets', label: 'Budgets' },
  { to: '/finance/net-worth', label: 'Net Worth' },
  { to: '/finance/retirement', label: 'Retirement' },
  { to: '/finance/recurring', label: 'Recurring' },
]

export default function FinanceLayout() {
  return (
    <div className="flex flex-col h-full overflow-y-auto overflow-x-hidden bg-background">
      {/* Sub-nav scrolls horizontally on mobile so all tabs stay reachable. */}
      <div className="flex items-center gap-1 px-4 py-2 shrink-0 border-b border-border overflow-x-auto whitespace-nowrap">
        <span className="text-sm font-semibold mr-3 text-text hidden sm:inline">Finance</span>
        {TABS.map((t) => (
          <NavLink
            key={t.to}
            to={t.to}
            className={({ isActive }) =>
              `shrink-0 px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${
                isActive ? 'bg-surface text-primary' : 'text-text-muted hover:text-text'
              }`
            }
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
