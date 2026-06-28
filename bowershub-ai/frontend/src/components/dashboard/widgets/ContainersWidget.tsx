import type { WidgetProps } from '../WidgetRegistry'

export default function ContainersWidget({ config, data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>

  const { containers = [], error } = data as { containers: { name: string; status: string; image: string; ports: string; uptime: string }[]; error: string | null }

  if (error && containers.length === 0) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>⚠ {error}</div>

  const links: Record<string, string> = config?.links ?? {}

  return (
    <div className="flex flex-col gap-1">
      {containers.map((c) => {
        const isRunning = c.status === 'running'
        const linkUrl = links[c.name]
        return (
          <div key={c.name} className="flex items-center gap-3 rounded-md px-3 py-2" style={{ opacity: isRunning ? 1 : 0.6, backgroundColor: 'color-mix(in srgb, var(--color-border) 20%, transparent)' }}>
            <span className="inline-block h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: isRunning ? 'var(--color-success)' : 'var(--color-text-muted)' }} />
            <div className="flex-1 min-w-0">
              {linkUrl ? (
                <a href={linkUrl} target="_blank" rel="noopener noreferrer" className="truncate text-sm font-medium hover:underline block" style={{ color: 'var(--color-primary)' }}>{c.name}</a>
              ) : (
                <span className="truncate text-sm font-medium block" style={{ color: 'var(--color-text)' }}>{c.name}</span>
              )}
              <span className="text-xs block" style={{ color: 'var(--color-text-muted)' }}>{c.uptime}</span>
            </div>
          </div>
        )
      })}
    </div>
  )
}
