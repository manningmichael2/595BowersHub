import type { WidgetProps } from '../WidgetRegistry'

function getDay(dateStr: string): string {
  return new Date(dateStr + 'T12:00:00').toLocaleDateString('en-US', { weekday: 'short' })
}

export default function ApiSpendWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No data</div>

  const d = (data.data ?? data) as { total_7d: number; per_day: { date: string; cost: number }[]; error?: string | null }
  if (d.error) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{d.error}</div>

  const perDay = d.per_day || []
  const max = perDay.length > 0 ? Math.max(...perDay.map(x => x.cost)) : 0

  return (
    <div className="flex flex-col gap-4">
      <div>
        <p className="text-xs uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>7-day total</p>
        <p className="text-2xl font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>${(d.total_7d || 0).toFixed(2)}</p>
      </div>
      {perDay.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {perDay.map(day => (
            <div key={day.date} className="flex items-center gap-2">
              <span className="w-8 shrink-0 text-xs text-right" style={{ color: 'var(--color-text-muted)' }}>{getDay(day.date)}</span>
              <div className="relative flex-1 h-4 rounded overflow-hidden" style={{ backgroundColor: 'var(--color-border)' }}>
                <div className="absolute inset-y-0 left-0 rounded" style={{ width: `${max > 0 ? (day.cost / max) * 100 : 0}%`, minWidth: day.cost > 0 ? '2px' : '0', backgroundColor: 'var(--color-accent, var(--color-primary))', opacity: 0.85 }} />
              </div>
              <span className="w-12 shrink-0 text-right text-xs font-medium tabular-nums" style={{ color: 'var(--color-text)' }}>${day.cost.toFixed(2)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
