import type { WidgetProps } from '../WidgetRegistry'

function fmt(n: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 }).format(n)
}

export default function FinanceSummaryWidget({ data }: WidgetProps) {
  if (!data || data.error) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{data?.message || 'No finance data'}</div>

  const d = data.data as { mtd_spending: number; mtd_income: number; top_categories: { category: string; total: number }[]; net_change: number; prev_month_spending: number; prev_month_income: number } | undefined
  if (!d) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No data</div>

  const isDown = d.net_change <= 0
  const max = d.top_categories.length > 0 ? Math.max(...d.top_categories.map(c => c.total)) : 0

  return (
    <div className="flex flex-col gap-4">
      {/* MTD Income & Spending */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>MTD Spending</p>
          <p className="text-xl font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>{fmt(d.mtd_spending)}</p>
        </div>
        <div className="text-right">
          <p className="text-xs uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>MTD Income</p>
          <p className="text-xl font-bold tabular-nums" style={{ color: 'var(--color-success)' }}>{fmt(d.mtd_income || 0)}</p>
        </div>
      </div>

      {/* Net change badge + prev month */}
      <div className="flex items-center justify-between text-xs" style={{ color: 'var(--color-text-muted)' }}>
        <span>Last month: {fmt(d.prev_month_spending)} spent / {fmt(d.prev_month_income || 0)} earned</span>
        <span className="inline-flex items-center rounded-full px-2 py-0.5 font-semibold" style={{ backgroundColor: `color-mix(in srgb, ${isDown ? 'var(--color-success)' : 'var(--color-danger)'} 15%, transparent)`, color: isDown ? 'var(--color-success)' : 'var(--color-danger)' }}>
          {isDown ? '↓' : '↑'} {fmt(Math.abs(d.net_change))}
        </span>
      </div>

      {/* Top Categories */}
      {d.top_categories.length > 0 && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>Top categories</p>
          {d.top_categories.slice(0, 5).map(cat => (
            <div key={cat.category} className="flex items-center gap-2">
              <span className="w-20 shrink-0 truncate text-xs" style={{ color: 'var(--color-text-muted)' }}>{cat.category.replace(/_/g, ' ')}</span>
              <div className="relative flex-1 h-4 rounded overflow-hidden" style={{ backgroundColor: 'var(--color-border)' }}>
                <div className="absolute inset-y-0 left-0 rounded" style={{ width: `${max > 0 ? (cat.total / max) * 100 : 0}%`, backgroundColor: 'var(--color-primary)', opacity: 0.85 }} />
              </div>
              <span className="w-14 shrink-0 text-right text-xs font-medium" style={{ color: 'var(--color-text)' }}>{fmt(cat.total)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
