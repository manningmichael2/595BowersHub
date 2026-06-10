import type { WidgetProps } from '../WidgetRegistry'

function fmtAmt(n: number): string {
  const abs = Math.abs(n)
  const f = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n < 0 ? `-$${f}` : `+$${f}`
}

function fmtDate(d: string): string {
  return new Date(d + 'T00:00:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export default function RecentTransactionsWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>
  if (data.error || !data.data) return <div className="text-sm" style={{ color: '#ef4444' }}>{data.message || 'Unable to load'}</div>

  const txns = (data.data as { transactions: { amount: number; description: string; category: string; posted_date: string }[] }).transactions || []
  if (txns.length === 0) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No recent transactions</div>

  return (
    <div className="flex flex-col gap-1">
      {txns.slice(0, 10).map((tx, i) => (
        <div key={i} className="flex flex-wrap items-center gap-x-2 gap-y-0.5 rounded px-2 py-1.5" style={{ backgroundColor: i % 2 === 0 ? 'transparent' : 'color-mix(in srgb, var(--color-border) 20%, transparent)' }}>
          <span className="shrink-0 text-sm font-medium tabular-nums" style={{ color: tx.amount >= 0 ? '#22c55e' : '#ef4444' }}>{fmtAmt(tx.amount)}</span>
          <span className="min-w-0 flex-1 truncate text-sm" style={{ color: 'var(--color-text)' }}>{tx.description}</span>
          <span className="shrink-0 text-xs" style={{ color: 'var(--color-text-muted)' }}>{tx.posted_date ? fmtDate(tx.posted_date) : ''}</span>
          {tx.category && <span className="rounded-full px-2 py-0.5 text-xs" style={{ backgroundColor: 'color-mix(in srgb, var(--color-primary) 20%, transparent)', color: 'var(--color-primary)' }}>{tx.category.replace(/_/g, ' ')}</span>}
        </div>
      ))}
    </div>
  )
}
