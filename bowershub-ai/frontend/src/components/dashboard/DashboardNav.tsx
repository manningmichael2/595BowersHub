import { useDashboardStore } from '../../stores/dashboard'

const PAGES = [
  { key: 'overview', label: 'Overview' },
  { key: 'finance', label: 'Finance' },
  { key: 'system', label: 'System' },
]

export default function DashboardNav() {
  const { activePage, setActivePage, layouts } = useDashboardStore()

  const availablePages = PAGES.filter(p => layouts[p.key])

  return (
    <nav className="flex gap-1" aria-label="Dashboard pages">
      {availablePages.map((page) => (
        <button
          key={page.key}
          onClick={() => setActivePage(page.key)}
          className="h-9 px-3 rounded-lg text-xs font-medium whitespace-nowrap transition-colors"
          style={{
            backgroundColor: activePage === page.key ? 'var(--color-primary)' : 'transparent',
            color: activePage === page.key ? 'var(--color-on-primary)' : 'var(--color-text-muted)',
          }}
          aria-current={activePage === page.key ? 'page' : undefined}
        >
          {page.label}
        </button>
      ))}
    </nav>
  )
}
