import type { WidgetProps } from '../WidgetRegistry'

export default function TailscaleWidget({ data }: WidgetProps) {
  if (!data) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Loading...</div>

  const d = data as { devices: { name: string; online: boolean; ip: string }[]; error?: string | null }

  if (d.error && (!d.devices || d.devices.length === 0)) return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>⚠ {d.error}</div>

  return (
    <div className="flex flex-col gap-1">
      {d.devices?.map(device => (
        <div key={device.name} className="flex items-center gap-3 rounded-md px-3 py-2" style={{ backgroundColor: 'color-mix(in srgb, var(--color-border) 20%, transparent)' }}>
          <span className="inline-block h-2.5 w-2.5 rounded-full flex-shrink-0" style={{ backgroundColor: device.online ? 'var(--color-success)' : 'var(--color-text-muted)' }} />
          <div className="flex-1 min-w-0">
            <span className="truncate text-sm font-medium block" style={{ color: device.online ? 'var(--color-text)' : 'var(--color-text-muted)' }}>{device.name}</span>
            <span className="text-xs font-mono block" style={{ color: 'var(--color-text-muted)' }}>{device.ip}</span>
          </div>
          <span className="text-xs flex-shrink-0" style={{ color: device.online ? 'var(--color-success)' : 'var(--color-text-muted)' }}>{device.online ? 'online' : 'offline'}</span>
        </div>
      ))}
    </div>
  )
}
