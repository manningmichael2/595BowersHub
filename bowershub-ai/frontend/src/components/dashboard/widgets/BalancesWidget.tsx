import type { WidgetProps } from '../WidgetRegistry'

function fmtCurrency(n: number): string {
  const abs = Math.abs(n)
  const formatted = abs.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return n < 0 ? `-$${formatted}` : `$${formatted}`
}

export default function BalancesWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>
  if (data.error || !data.data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{data.message || 'Unable to load'}</div>

  const { accounts_by_type, net_worth } = data.data as { accounts_by_type: Record<string, { name: string; balance: number }[]>; net_worth: number }

  const groups = Object.entries(accounts_by_type).sort(([a], [b]) => a.localeCompare(b))

  return (
    <div className="flex flex-col gap-3">
      {/* Net Worth */}
      <div className="text-center pb-2" style={{ borderBottom: '1px solid var(--color-border)' }}>
        <p className="text-xs font-medium uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>Net Worth</p>
        <p className="text-2xl font-bold" style={{ color: '#22c55e' }}>{fmtCurrency(net_worth)}</p>
      </div>

      {/* Accounts by group */}
      {groups.map(([group, accounts]) => {
        if (!accounts || accounts.length === 0) return null
        return (
          <div key={group}>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide" style={{ color: 'var(--color-text-muted)' }}>{group}</h4>
            <div className="flex flex-col gap-0.5">
              {accounts.map(a => (
                <div key={a.name} className="flex items-center justify-between gap-2 rounded px-2 py-1 text-sm">
                  <span className="min-w-0 truncate" style={{ color: 'var(--color-text)' }}>{a.name}</span>
                  <span className="shrink-0 font-medium tabular-nums" style={{ color: a.balance < 0 ? '#ef4444' : 'var(--color-text)' }}>{fmtCurrency(a.balance)}</span>
                </div>
              ))}
            </div>
          </div>
        )
      })}
    </div>
  )
}
