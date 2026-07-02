import { useState } from 'react'

/** A dismissible/actionable card emitted by the dashboard stream's `actions`. */
export interface DashboardAction {
  id: string
  level: 'info' | 'success' | 'warning' | 'error'
  title: string
  detail?: string
}

const LEVEL: Record<DashboardAction['level'], { bg: string; fg: string }> = {
  info: { bg: 'rgb(var(--color-primary-rgb) / 0.10)', fg: 'var(--color-primary)' },
  success: { bg: 'rgb(var(--color-success-rgb) / 0.10)', fg: 'var(--color-success)' },
  warning: { bg: 'rgb(var(--color-warning-rgb) / 0.12)', fg: 'var(--color-warning)' },
  error: { bg: 'rgb(var(--color-danger-rgb) / 0.12)', fg: 'var(--color-danger)' },
}

/**
 * Action Center — a dynamic top-row strip of cards for critical system states
 * (e.g. "Disk /data at 96%"), derived server-side from the SSE cache. Cards are
 * dismissible (per-session, client-side). The whole strip renders nothing when
 * there are no live, undismissed actions (R2.1).
 */
export function ActionCenter({ actions }: { actions: DashboardAction[] }) {
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const visible = actions.filter((a) => !dismissed.has(a.id))
  if (visible.length === 0) return null

  return (
    <div className="flex flex-col gap-2 px-4 pt-4" aria-label="Alerts" role="region">
      {visible.map((a) => {
        const c = LEVEL[a.level] ?? LEVEL.info
        return (
          <div
            key={a.id}
            className="flex items-start gap-3 rounded-lg px-4 py-3"
            style={{ backgroundColor: c.bg, border: `1px solid ${c.fg}` }}
          >
            <span className="mt-0.5 h-2 w-2 shrink-0 rounded-full" style={{ backgroundColor: c.fg }} aria-hidden />
            <div className="min-w-0 flex-1">
              <div className="text-sm font-semibold" style={{ color: c.fg }}>{a.title}</div>
              {a.detail && (
                <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>{a.detail}</div>
              )}
            </div>
            <button
              onClick={() => setDismissed((prev) => new Set(prev).add(a.id))}
              aria-label={`Dismiss ${a.title}`}
              className="shrink-0 rounded-md px-2 py-0.5 text-sm transition-opacity hover:opacity-70"
              style={{ color: 'var(--color-text-muted)' }}
            >
              ✕
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default ActionCenter
