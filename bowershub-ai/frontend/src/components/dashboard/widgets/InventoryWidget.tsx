import type { WidgetProps } from '../WidgetRegistry'

function formatName(t: string): string {
  return t.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

export default function InventoryWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No data</div>

  const d = (data.data ?? data) as { items?: { table: string; count: number }[]; error?: string | null }
  if (d.error) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{d.error}</div>

  const items = d.items || []
  if (items.length === 0) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No inventory</div>

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
      {items.map(item => (
        <div key={item.table} className="flex flex-col items-center justify-center rounded-lg px-4 py-3" style={{ backgroundColor: 'color-mix(in srgb, var(--color-border) 30%, transparent)' }}>
          <span className="text-2xl font-bold tabular-nums" style={{ color: 'var(--color-text)' }}>{item.count}</span>
          <span className="mt-1 text-xs" style={{ color: 'var(--color-text-muted)' }}>{formatName(item.table)}</span>
        </div>
      ))}
    </div>
  )
}
