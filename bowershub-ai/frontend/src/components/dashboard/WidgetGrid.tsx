import React, { Suspense, useMemo, useCallback } from 'react'
import { Responsive, WidthProvider } from 'react-grid-layout/legacy'
import type { Layout, LayoutItem } from 'react-grid-layout/legacy'
import 'react-grid-layout/css/styles.css'
import 'react-resizable/css/styles.css'
import { WidgetInstance, WidgetType, useDashboardStore } from '../../stores/dashboard'
import { getWidgetComponent } from './WidgetRegistry'
import WidgetShell from './WidgetShell'
import { useDashboardWidget } from '../../hooks/useDashboardWidget'
import { endpointToStreamKey } from './streamKey'

const ResponsiveGridLayout = WidthProvider(Responsive)

interface WidgetGridProps {
  widgets: WidgetInstance[]
  availableWidgets: WidgetType[]
  editMode?: boolean
  onRemove?: (widgetKey: string) => void
  /**
   * When provided (Dashboard V2), widgets read their data from this SSE cache
   * keyed by stream key instead of each polling its own endpoint. Absent →
   * legacy per-widget polling (V1).
   */
  streamData?: Record<string, unknown>
}

// Default sizes for widget types (w in grid units out of 6, h in grid units)
const DEFAULT_SIZES: Record<string, { w: number; h: number }> = {
  weather: { w: 2, h: 3 },
  finance_summary: { w: 2, h: 3 },
  finance_balances: { w: 2, h: 4 },
  recent_transactions: { w: 3, h: 3 },
  system_health: { w: 2, h: 3 },
  containers: { w: 2, h: 4 },
  inventory: { w: 2, h: 2 },
  knowledge_base: { w: 2, h: 3 },
  recent_emails: { w: 2, h: 3 },
  tailscale_devices: { w: 2, h: 3 },
  api_spend: { w: 2, h: 3 },
  sports_scores: { w: 2, h: 4 },
  news: { w: 2, h: 3 },
}

/** Presentational card shell — data-source-agnostic (fed by polling or stream). */
function WidgetBody({
  instance, widgetDef, data, error, isLoading, isStale, lastFetched, onRefresh, editMode, onRemove,
}: {
  instance: WidgetInstance
  widgetDef: WidgetType
  data: unknown
  error: string | null
  isLoading: boolean
  isStale: boolean
  lastFetched: Date | null
  onRefresh?: () => void
  editMode: boolean
  onRemove?: (key: string) => void
}) {
  const definition = getWidgetComponent(instance.widget_key)
  if (!definition) return null

  const Component = definition.component
  const config = { ...widgetDef.default_config, ...instance.config_overrides }

  return (
    <div className="h-full relative overflow-hidden">
      {editMode && onRemove && (
        <button
          onClick={(e) => { e.stopPropagation(); onRemove(instance.widget_key) }}
          className="absolute top-1 right-1 z-20 w-6 h-6 flex items-center justify-center rounded-full text-xs font-bold"
          style={{ backgroundColor: 'var(--color-danger)', color: 'var(--color-on-danger)' }}
          title="Remove widget"
        >
          ✕
        </button>
      )}
      <WidgetShell
        displayName={widgetDef.display_name}
        isLoading={isLoading}
        error={error}
        isStale={isStale}
        lastFetched={lastFetched}
        onRefresh={onRefresh}
      >
        <Suspense fallback={<div className="animate-pulse h-16 rounded" style={{ backgroundColor: 'var(--color-surface)' }} />}>
          <Component config={config} widgetDef={widgetDef} data={data} />
        </Suspense>
      </WidgetShell>
    </div>
  )
}

/** V1: each widget polls its own endpoint. */
function PollingWidgetCard(props: { instance: WidgetInstance; widgetDef: WidgetType; editMode: boolean; onRemove?: (key: string) => void }) {
  const { instance, widgetDef } = props
  const config = { ...widgetDef.default_config, ...instance.config_overrides }
  const pollingInterval = config.polling_interval_ms || 60000
  const { data, error, isLoading, isStale, lastFetched, refresh } = useDashboardWidget({
    endpoint: widgetDef.data_endpoint,
    pollingInterval,
  })
  return <WidgetBody {...props} data={data} error={error} isLoading={isLoading} isStale={isStale} lastFetched={lastFetched} onRefresh={refresh} />
}

/** V2: widget data comes from the shared SSE cache — no per-widget request. */
function StreamWidgetCard(props: { instance: WidgetInstance; widgetDef: WidgetType; editMode: boolean; onRemove?: (key: string) => void; streamData: Record<string, unknown> }) {
  const { widgetDef, streamData } = props
  const data = streamData[endpointToStreamKey(widgetDef.data_endpoint)]
  // Undefined = the publisher hasn't produced this key yet (pre-hydration);
  // the widget's own `!data` branch renders its loading state.
  return <WidgetBody {...props} data={data} error={null} isLoading={data === undefined} isStale={false} lastFetched={null} />
}

export function WidgetGrid({ widgets, availableWidgets, editMode = false, onRemove, streamData }: WidgetGridProps) {
  const widgetDefMap = useMemo(() => new Map(availableWidgets.map((w) => [w.widget_key, w])), [availableWidgets])
  const { reorderWidgets, activePage } = useDashboardStore()

  // Build layout from widget instances
  const currentLayout = useMemo((): LayoutItem[] => {
    return widgets.map((instance, index) => {
      const saved = instance.config_overrides?._layout
      const defaults = DEFAULT_SIZES[instance.widget_key] || { w: 1, h: 2 }

      if (saved) {
        return { i: instance.widget_key, x: saved.x, y: saved.y, w: saved.w, h: saved.h, minW: 1, minH: 1 }
      }

      // Auto-place in 6-column grid
      const col = (index * 2) % 6
      const row = Math.floor((index * 2) / 6) * defaults.h
      return { i: instance.widget_key, x: col, y: row, w: defaults.w, h: defaults.h, minW: 1, minH: 1 }
    })
  }, [widgets])

  const handleLayoutChange = useCallback((newLayout: LayoutItem[]) => {
    if (!editMode) return

    // Save layout positions into config_overrides._layout
    const updatedWidgets = widgets.map(w => {
      const layoutItem = newLayout.find(l => l.i === w.widget_key)
      if (!layoutItem) return w
      return {
        ...w,
        config_overrides: {
          ...w.config_overrides,
          _layout: { x: layoutItem.x, y: layoutItem.y, w: layoutItem.w, h: layoutItem.h },
        },
      }
    })
    reorderWidgets(activePage, updatedWidgets)
  }, [editMode, widgets, activePage, reorderWidgets])

  return (
    <div className="p-4 overflow-x-hidden">
      <ResponsiveGridLayout
        layouts={{ lg: currentLayout, md: currentLayout, sm: currentLayout.map(l => ({ ...l, x: 0, w: 1 })) }}
        breakpoints={{ lg: 1024, md: 640, sm: 0 }}
        cols={{ lg: 6, md: 4, sm: 1 }}
        rowHeight={80}
        isDraggable={editMode}
        isResizable={editMode}
        onLayoutChange={(layout) => handleLayoutChange(layout as unknown as LayoutItem[])}
        margin={[12, 12] as [number, number]}
        containerPadding={[0, 0] as [number, number]}
      >
        {widgets.map((instance) => {
          const widgetDef = widgetDefMap.get(instance.widget_key)
          if (!widgetDef) return <div key={instance.widget_key} />

          return (
            <div key={instance.widget_key} className={editMode ? 'ring-1 ring-[var(--color-primary)] rounded-lg' : ''} style={{ overflow: 'hidden' }}>
              <div className="h-full w-full">
                {streamData
                  ? <StreamWidgetCard instance={instance} widgetDef={widgetDef} editMode={editMode} onRemove={onRemove} streamData={streamData} />
                  : <PollingWidgetCard instance={instance} widgetDef={widgetDef} editMode={editMode} onRemove={onRemove} />}
              </div>
            </div>
          )
        })}
      </ResponsiveGridLayout>
    </div>
  )
}

export default WidgetGrid
