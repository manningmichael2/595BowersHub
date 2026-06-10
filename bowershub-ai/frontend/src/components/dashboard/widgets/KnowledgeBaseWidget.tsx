import type { WidgetProps } from '../WidgetRegistry'

export default function KnowledgeBaseWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No data</div>

  const d = data as { file_count: number; recent_files?: { name: string; path: string }[]; error?: string | null }
  if (d.error) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{d.error}</div>

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-3xl font-bold" style={{ color: 'var(--color-text)' }}>{d.file_count}</span>
        <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>knowledge files</span>
      </div>
      {d.recent_files && d.recent_files.length > 0 && (
        <div>
          <p className="text-xs font-medium uppercase tracking-wide mb-1" style={{ color: 'var(--color-text-muted)' }}>Recently added</p>
          <div className="flex flex-col gap-0.5">
            {d.recent_files.map((f, i) => (
              <div key={i} className="flex items-center gap-2 text-xs py-0.5">
                <span style={{ color: 'var(--color-primary)' }}>📄</span>
                <span className="truncate" style={{ color: 'var(--color-text)' }} title={f.path}>{f.name}</span>
                <span className="shrink-0 ml-auto" style={{ color: 'var(--color-text-muted)' }}>{f.path.split('/')[0]}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
