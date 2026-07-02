import { useDashboardStream } from '../../hooks/useDashboardStream'
import { useDashboardStore } from '../../stores/dashboard'
import { WidgetGrid } from './WidgetGrid'
import DashboardNav from './DashboardNav'
import { TaskReelWidget, type AgentEvent } from './TaskReelWidget'
import { ActionCenter, type DashboardAction } from './ActionCenter'

/**
 * Dashboard V2 — the same per-user widget layout as V1, but every widget is fed
 * from a single Server-Sent-Events stream (`/api/dashboard/stream`) instead of
 * 13 independent polling loops. The layout is per-user (loaded by the store);
 * widget *data* is household-global and pushed from the shared publisher cache.
 * Opt-in via the `use_experimental_dashboard` setting.
 */
export default function DashboardV2() {
  const { isConnected, widgetData } = useDashboardStream()
  const layouts = useDashboardStore((s) => s.layouts)
  const activePage = useDashboardStore((s) => s.activePage)
  const availableWidgets = useDashboardStore((s) => s.availableWidgets)

  const widgets = layouts[activePage]?.widgets || []
  const events = (widgetData.agent_events as AgentEvent[] | undefined) ?? []
  const actions = (widgetData.actions as DashboardAction[] | undefined) ?? []

  return (
    <div
      className="flex flex-col h-full overflow-y-auto overflow-x-hidden"
      style={{ backgroundColor: 'var(--color-background)' }}
    >
      <div
        className="flex items-center gap-2 px-3 py-2 shrink-0"
        style={{ borderBottom: '1px solid var(--color-border)' }}
      >
        <div className="flex-1 overflow-x-auto">
          <DashboardNav />
        </div>
        <LiveIndicator connected={isConnected} />
      </div>

      <ActionCenter actions={actions} />

      <WidgetGrid widgets={widgets} availableWidgets={availableWidgets} streamData={widgetData} />

      <div className="px-4 pb-4">
        <TaskReelWidget events={events} />
      </div>
    </div>
  )
}

/** Small stream-status pill. Green pulse = live SSE; amber = reconnecting. */
function LiveIndicator({ connected }: { connected: boolean }) {
  return (
    <span
      role="status"
      aria-live="polite"
      className="flex items-center gap-1.5 shrink-0 rounded-full px-2.5 py-1 text-xs font-medium"
      style={{
        backgroundColor: connected ? 'rgb(var(--color-success-rgb) / 0.12)' : 'rgb(var(--color-warning-rgb) / 0.12)',
        color: connected ? 'var(--color-success)' : 'var(--color-warning)',
      }}
      title={connected ? 'Live — streaming updates' : 'Reconnecting to the live stream'}
    >
      <span
        className={connected ? 'motion-safe:animate-pulse' : ''}
        style={{
          width: 7,
          height: 7,
          borderRadius: '9999px',
          backgroundColor: connected ? 'var(--color-success)' : 'var(--color-warning)',
        }}
        aria-hidden
      />
      {connected ? 'Live' : 'Reconnecting…'}
    </span>
  )
}
