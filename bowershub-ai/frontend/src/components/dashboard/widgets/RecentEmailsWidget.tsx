import type { WidgetProps } from '../WidgetRegistry'

export default function RecentEmailsWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No data</div>

  const d = data as { unread_count: number | null; recent_subjects: string[]; error?: string | null }

  if (d.error) return (
    <div className="flex flex-col items-center gap-2 py-4 text-center">
      <span className="text-2xl">📭</span>
      <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{d.error}</p>
    </div>
  )

  return (
    <div className="flex flex-col gap-3">
      {d.unread_count != null && (
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center justify-center rounded-full px-2.5 py-0.5 text-xs font-bold" style={{ backgroundColor: d.unread_count > 0 ? 'var(--color-primary)' : 'var(--color-border)', color: d.unread_count > 0 ? '#fff' : 'var(--color-text-muted)' }}>{d.unread_count}</span>
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>unread</span>
        </div>
      )}
      {d.recent_subjects?.length > 0 ? (
        <ul className="flex flex-col gap-1.5">
          {d.recent_subjects.slice(0, 5).map((s, i) => (
            <li key={i} className="truncate text-sm" style={{ color: 'var(--color-text)' }} title={s}>• {s}</li>
          ))}
        </ul>
      ) : <p className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No recent emails</p>}
    </div>
  )
}
