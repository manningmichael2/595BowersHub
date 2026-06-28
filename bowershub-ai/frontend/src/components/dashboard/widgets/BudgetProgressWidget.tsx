import type { WidgetProps } from '../WidgetRegistry'
import { budgetTone, type BudgetTone } from '../../../lib/budget'

function fmt(n: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(n)
}

const TONE_COLOR: Record<BudgetTone, string> = { ok: 'var(--color-success)', warn: 'var(--color-warning)', over: 'var(--color-danger)' }

interface Row { category: string; budgeted: number; actual: number; remaining: number | null }

export default function BudgetProgressWidget({ data }: WidgetProps) {
  if (!data || data.error) {
    return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{data?.message || 'No budget data'}</div>
  }
  const d = data.data as { month: string; categories: Row[] } | undefined
  if (!d || d.categories.length === 0) {
    return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No budgets set this month.</div>
  }

  return (
    <div className="flex flex-col gap-2">
      {d.categories.map((r) => {
        const tone = budgetTone(r.actual, r.budgeted)
        const pct = r.budgeted > 0 ? Math.min(100, (r.actual / r.budgeted) * 100) : 0
        return (
          <div key={r.category} className="flex flex-col gap-1">
            <div className="flex justify-between text-xs" style={{ color: 'var(--color-text)' }}>
              <span>{r.category}</span>
              <span className="tabular-nums" style={{ color: 'var(--color-text-muted)' }}>
                {fmt(r.actual)} / {fmt(r.budgeted)}
              </span>
            </div>
            <div style={{ height: 6, borderRadius: 3, backgroundColor: 'var(--color-border)' }}>
              <div style={{ width: `${pct}%`, height: '100%', borderRadius: 3, backgroundColor: TONE_COLOR[tone] }} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
