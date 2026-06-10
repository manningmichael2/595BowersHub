import type { WidgetProps } from '../WidgetRegistry'

function getColor(percent: number): string {
  if (percent >= 90) return '#ef4444'
  if (percent >= 70) return '#eab308'
  return '#22c55e'
}

function formatBytes(bytes: number): string {
  const gb = bytes / (1024 * 1024 * 1024)
  if (gb >= 1) return `${gb.toFixed(1)} GB`
  return `${(bytes / (1024 * 1024)).toFixed(0)} MB`
}

function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  if (days > 0) return `${days}d ${hours}h`
  if (hours > 0) return `${hours}h`
  return `${Math.floor((seconds % 3600) / 60)}m`
}

function Bar({ percent, label, detail }: { percent: number; label: string; detail?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center justify-between text-xs">
        <span style={{ color: 'var(--color-text)' }}>{label}</span>
        <span style={{ color: 'var(--color-text-muted)' }}>{detail || `${percent.toFixed(1)}%`}</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(percent, 100)}%`, backgroundColor: getColor(percent) }} />
      </div>
    </div>
  )
}

export default function SystemHealthWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>No data</div>

  const h = data as { cpu_percent: number; memory: { used_bytes: number; total_bytes: number; percent: number }; disk: { mount: string; used_bytes: number; total_bytes: number; percent: number }[]; uptime_seconds: number; errors?: Record<string, string> }

  return (
    <div className="flex flex-col gap-3">
      <Bar percent={h.cpu_percent} label="CPU" detail={`${h.cpu_percent.toFixed(1)}%`} />
      {h.memory && <Bar percent={h.memory.percent} label="Memory" detail={`${formatBytes(h.memory.used_bytes)} / ${formatBytes(h.memory.total_bytes)}`} />}
      {h.disk?.map((d) => <Bar key={d.mount} percent={d.percent} label={`Disk ${d.mount}`} detail={`${formatBytes(d.used_bytes)} / ${formatBytes(d.total_bytes)}`} />)}
      {h.uptime_seconds != null && (
        <div className="flex items-center justify-between pt-1 text-xs">
          <span style={{ color: 'var(--color-text-muted)' }}>Uptime</span>
          <span style={{ color: 'var(--color-text)' }}>{formatUptime(h.uptime_seconds)}</span>
        </div>
      )}
    </div>
  )
}
