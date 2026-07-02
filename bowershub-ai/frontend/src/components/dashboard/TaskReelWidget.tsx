import { useState } from 'react'
import { toast } from '../../stores/toast'
import { api } from '../../services/api'

/** A background/system event from the SSE stream's `agent_events` array. */
export interface AgentEvent {
  id: number
  created_at: string
  source: string
  message: string
  level: 'info' | 'success' | 'warning' | 'error'
  action_payload?: AgentAction | null
}

interface AgentAction {
  label: string
  type: string // 'mutation'
  endpoint: string
  method?: string // POST | PATCH | PUT | DELETE (default POST)
  body?: unknown
}

const LEVEL_COLOR: Record<AgentEvent['level'], string> = {
  info: 'var(--color-text-muted)',
  success: 'var(--color-success)',
  warning: 'var(--color-warning)',
  error: 'var(--color-danger)',
}

/**
 * Task Reel — a scrolling log of recent background/agent activity (categorizer,
 * SimpleFin sync, embedding worker, …), fed live from the dashboard SSE stream.
 * Events may carry an inline `action_payload` rendered as a one-tap mutation
 * button, so the user can act (e.g. "Recategorize") without opening chat.
 */
export function TaskReelWidget({ events }: { events: AgentEvent[] }) {
  return (
    <section
      aria-label="Recent activity"
      className="flex flex-col rounded-lg overflow-hidden"
      style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <header
        className="px-4 py-3 text-sm font-semibold shrink-0"
        style={{ color: 'var(--color-text)', borderBottom: '1px solid var(--color-border)' }}
      >
        Activity
      </header>
      {/* No nested scroll: an inner overflow container traps touch-scroll on
          mobile (the page can't scroll past the card). Cap to the most-recent
          few and let the page scroll as one surface. */}
      <div>
        {events.length === 0 ? (
          <div className="p-4 text-sm" style={{ color: 'var(--color-text-muted)' }}>
            No recent activity.
          </div>
        ) : (
          events.slice(0, 8).map((e) => <EventRow key={e.id} event={e} />)
        )}
      </div>
    </section>
  )
}

function EventRow({ event }: { event: AgentEvent }) {
  const [busy, setBusy] = useState(false)
  const [done, setDone] = useState(false)
  const color = LEVEL_COLOR[event.level] ?? LEVEL_COLOR.info
  const action = event.action_payload

  async function runAction() {
    if (!action) return
    setBusy(true)
    try {
      const method = (action.method || 'POST').toUpperCase()
      if (method === 'PATCH') await api.patch(action.endpoint, action.body)
      else if (method === 'PUT') await api.put(action.endpoint, action.body)
      else if (method === 'DELETE') await api.delete(action.endpoint)
      else await api.post(action.endpoint, action.body)
      toast.success(`${action.label} done`)
      setDone(true)
    } catch (err: any) {
      toast.error(`${action.label} failed: ${err?.response?.data?.detail || 'error'}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="flex items-start gap-2 px-4 py-2 text-sm"
      style={{ borderTop: '1px solid var(--color-border)' }}
    >
      <span
        className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full"
        style={{ backgroundColor: color }}
        aria-hidden
      />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-xs font-medium uppercase tracking-wide" style={{ color }}>
            {event.source}
          </span>
          <span className="text-xs" style={{ color: 'var(--color-text-muted)' }}>
            {relativeTime(event.created_at)}
          </span>
        </div>
        <div className="truncate" style={{ color: 'var(--color-text)' }}>
          {event.message}
        </div>
      </div>
      {action && (
        <button
          onClick={runAction}
          disabled={busy || done}
          className="shrink-0 rounded-md px-2.5 py-1 text-xs font-medium transition-opacity hover:opacity-80 disabled:opacity-50"
          style={{ backgroundColor: 'rgb(var(--color-primary-rgb) / 0.12)', color: 'var(--color-primary)' }}
        >
          {done ? '✓ Done' : busy ? '…' : action.label}
        </button>
      )}
    </div>
  )
}

function relativeTime(iso: string): string {
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return ''
  const sec = Math.max(0, Math.floor((Date.now() - then) / 1000))
  if (sec < 60) return 'just now'
  const min = Math.floor(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr}h ago`
  return `${Math.floor(hr / 24)}d ago`
}

export default TaskReelWidget
