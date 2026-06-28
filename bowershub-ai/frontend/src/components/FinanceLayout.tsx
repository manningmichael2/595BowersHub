/**
 * FinanceLayout — the single Finance hub. One nav entry (/finance) with sub-tabs
 * for every finance tool. Provides the shared scroll container; chrome offsets
 * are owned by the app shell (R3.4), so each tool just renders via <Outlet>.
 */
import { Outlet } from 'react-router-dom'
import { SecondaryNav, type SecondaryNavItem } from './shell/SecondaryNav'

const TABS: SecondaryNavItem[] = [
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
      {/* Shared secondary-nav primitive (R3.3) — consistent across sections. */}
      <SecondaryNav items={TABS} label="Finance" />
      <div className="flex-1 min-h-0">
        <Outlet />
      </div>
    </div>
  )
}
