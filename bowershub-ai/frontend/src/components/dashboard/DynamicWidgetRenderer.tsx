/**
 * Renders an LLM-generated widget from a strict JSON spec (Dashboard V2 Task 8,
 * Generative UI). The shapes here mirror the server-side validator in
 * `backend/services/generated_widgets.py` — keep them in sync. Anything that
 * doesn't validate renders a small fallback rather than throwing.
 */
export type WidgetSpec =
  | { type: 'metric'; title: string; value: string; label?: string; delta?: string; delta_positive?: boolean }
  | { type: 'list'; title: string; items: string[] }
  | { type: 'bar'; title: string; rows: { label: string; value: number }[] }

export function DynamicWidgetRenderer({ spec }: { spec: WidgetSpec }) {
  return (
    <section
      className="rounded-lg overflow-hidden"
      style={{ backgroundColor: 'var(--color-surface)', border: '1px solid var(--color-border)' }}
    >
      <header
        className="flex items-center gap-2 px-4 py-3 text-sm font-semibold"
        style={{ color: 'var(--color-text)', borderBottom: '1px solid var(--color-border)' }}
      >
        <span aria-hidden>✨</span>
        <span className="truncate">{spec.title}</span>
      </header>
      <div className="p-4">{renderBody(spec)}</div>
    </section>
  )
}

function renderBody(spec: WidgetSpec) {
  switch (spec.type) {
    case 'metric':
      return (
        <div>
          <div className="text-2xl font-bold" style={{ color: 'var(--color-text)' }}>{spec.value}</div>
          <div className="mt-1 flex items-center gap-2 text-xs">
            {spec.label && <span style={{ color: 'var(--color-text-muted)' }}>{spec.label}</span>}
            {spec.delta && (
              <span style={{ color: spec.delta_positive ? 'var(--color-success)' : 'var(--color-danger)' }}>
                {spec.delta}
              </span>
            )}
          </div>
        </div>
      )
    case 'list':
      return (
        <ul className="flex flex-col gap-1.5 text-sm">
          {spec.items.map((it, i) => (
            <li key={i} className="flex items-start gap-2" style={{ color: 'var(--color-text)' }}>
              <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full" style={{ backgroundColor: 'var(--color-primary)' }} aria-hidden />
              <span className="min-w-0 break-words">{it}</span>
            </li>
          ))}
        </ul>
      )
    case 'bar': {
      const max = Math.max(1, ...spec.rows.map((r) => (Number.isFinite(r.value) ? r.value : 0)))
      return (
        <div className="flex flex-col gap-2">
          {spec.rows.map((r, i) => (
            <div key={i} className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-xs">
                <span className="truncate" style={{ color: 'var(--color-text)' }}>{r.label}</span>
                <span style={{ color: 'var(--color-text-muted)' }}>{r.value}</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full" style={{ backgroundColor: 'var(--color-border)' }}>
                <div className="h-full rounded-full" style={{ width: `${Math.max(0, Math.min(100, (r.value / max) * 100))}%`, backgroundColor: 'var(--color-primary)' }} />
              </div>
            </div>
          ))}
        </div>
      )
    }
    default:
      return <div className="text-sm" style={{ color: 'var(--color-text-muted)' }}>Unsupported widget.</div>
  }
}

export default DynamicWidgetRenderer
