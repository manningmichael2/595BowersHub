import { useEffect, useState, useCallback } from 'react'
import { api } from '../../services/api'
import { DynamicWidgetRenderer, type WidgetSpec } from './DynamicWidgetRenderer'

interface GeneratedWidget {
  id: string
  spec: WidgetSpec
}

/**
 * Renders the signed-in user's LLM-generated dashboard widgets. Refetches on
 * mount and whenever the SSE stream bumps `layout_epoch` (a generated widget was
 * added/removed somewhere) — each client pulls its OWN `/api/dashboard/generated`,
 * so the household-global stream never carries per-user widget data.
 */
export function GeneratedWidgets({ epoch }: { epoch: number }) {
  const [widgets, setWidgets] = useState<GeneratedWidget[]>([])

  const load = useCallback(async () => {
    try {
      const res = await api.get<GeneratedWidget[]>('/api/dashboard/generated')
      setWidgets(Array.isArray(res.data) ? res.data : [])
    } catch {
      /* transient — keep whatever we have */
    }
  }, [])

  useEffect(() => {
    load()
  }, [load, epoch])

  async function dismiss(id: string) {
    setWidgets((w) => w.filter((x) => x.id !== id)) // optimistic
    try {
      await api.delete(`/api/dashboard/generated/${id}`)
    } catch {
      load() // roll back to server truth
    }
  }

  if (widgets.length === 0) return null

  return (
    <div className="grid grid-cols-1 gap-3 px-4 pb-4 sm:grid-cols-2 lg:grid-cols-3">
      {widgets.map((w) => (
        <div key={w.id} className="relative">
          <button
            onClick={() => dismiss(w.id)}
            aria-label={`Dismiss ${w.spec?.title ?? 'widget'}`}
            className="absolute right-1.5 top-1.5 z-10 rounded-md px-1.5 py-0.5 text-sm transition-opacity hover:opacity-70"
            style={{ color: 'var(--color-text-muted)' }}
          >
            ✕
          </button>
          <DynamicWidgetRenderer spec={w.spec} />
        </div>
      ))}
    </div>
  )
}

export default GeneratedWidgets
