/**
 * InsightReview — the proactive finance insights surface (R2.5, R2.6, R5.2).
 *
 * Lists active insights ranked by dollar impact, each with its explanation +
 * figures, and per-insight actions (dismiss, mark-actioned) that need no later
 * code. The "always categorize {merchant} as {category}" rule-create action is
 * added in Task 12. Tokenized Tailwind.
 */
import { useCallback, useEffect, useState } from 'react'
import { toast } from '../stores/toast'
import { financeInsights, type Insight, type InsightStatus } from '../services/financeInsights'

const STATUS_TABS: InsightStatus[] = ['active', 'dismissed', 'actioned']

export default function InsightsPage() {
  const [status, setStatus] = useState<InsightStatus>('active')
  const [items, setItems] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setItems(await financeInsights.list(status))
    } catch {
      toast.error('Could not load insights.')
    } finally {
      setLoading(false)
    }
  }, [status])

  useEffect(() => {
    load()
  }, [load])

  async function act(id: number, fn: (id: number) => Promise<void>, label: string) {
    try {
      await fn(id)
      toast.success(label)
      await load()
    } catch {
      toast.error('Action failed.')
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <h1 className="text-lg font-semibold text-text mb-1">Insights</h1>
      <p className="text-sm text-text-muted mb-4">
        Proactive findings from your spending — duplicate charges, price hikes, forgotten trials,
        unusual activity. Ranked by dollar impact.
      </p>

      <div className="flex gap-1 mb-4">
        {STATUS_TABS.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setStatus(s)}
            className={`px-3 py-1 rounded-md text-xs font-medium capitalize ${
              status === s ? 'bg-primary text-on-primary' : 'text-text-muted hover:text-text'
            }`}
          >
            {s}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="text-sm text-text-muted">Loading…</div>
      ) : items.length === 0 ? (
        <div className="rounded-md border border-border bg-surface px-4 py-6 text-sm text-text-muted text-center">
          {status === 'active' ? 'No insights right now — all clear. 🎉' : `No ${status} insights.`}
        </div>
      ) : (
        <ul className="space-y-3" data-testid="insight-list">
          {items.map((it) => (
            <li
              key={it.id}
              className="rounded-md border border-border bg-surface px-4 py-3"
              data-testid="insight-row"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="text-xs uppercase tracking-wide text-text-muted">
                    {it.insight_type.replace(/_/g, ' ')} · {it.period}
                  </div>
                  <div className="text-sm text-text mt-0.5">{it.reason}</div>
                </div>
                <div className="text-sm font-semibold text-text shrink-0">
                  ${it.dollar_impact.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                </div>
              </div>

              {Object.keys(it.figures || {}).length > 0 && (
                <pre className="mt-2 overflow-x-auto rounded bg-surface-dark px-2 py-1 text-xs text-text-muted">
                  {JSON.stringify(it.figures, null, 0)}
                </pre>
              )}

              <div className="mt-2 flex gap-2">
                {it.status === 'active' ? (
                  <>
                    <button
                      type="button"
                      onClick={() => act(it.id, financeInsights.action, 'Marked as handled')}
                      className="rounded border border-border px-2 py-1 text-xs text-text hover:border-primary"
                    >
                      Mark handled
                    </button>
                    <button
                      type="button"
                      onClick={() => act(it.id, financeInsights.dismiss, 'Dismissed')}
                      className="rounded border border-border px-2 py-1 text-xs text-text-muted hover:text-text"
                    >
                      Dismiss
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    onClick={() => act(it.id, financeInsights.reopen, 'Reopened')}
                    className="rounded border border-border px-2 py-1 text-xs text-text hover:border-primary"
                  >
                    Reopen
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
