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
import { confirm } from '../stores/confirm'
import { financeInsights, type Insight, type InsightStatus } from '../services/financeInsights'
import { financeRules, type ParsedRule } from '../services/financeRules'
import { financeReview, type CategoryOption } from '../services/financeReview'

const STATUS_TABS: InsightStatus[] = ['active', 'dismissed', 'actioned']

/** Render one figure value readably instead of dumping raw JSON. */
function formatFigure(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') {
    return Number.isInteger(v)
      ? v.toLocaleString()
      : v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  }
  if (typeof v === 'boolean') return v ? 'Yes' : 'No'
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

/** Natural-language rule composer: type a rule in English, preview how many
 *  transactions it affects (validated server-side), then commit it. */
function NlRuleComposer({ onCreated }: { onCreated: () => void }) {
  const [text, setText] = useState('')
  const [parsed, setParsed] = useState<ParsedRule | null>(null)
  const [busy, setBusy] = useState(false)

  async function preview() {
    const t = text.trim()
    if (!t || busy) return
    setBusy(true)
    setParsed(null)
    try {
      setParsed(await financeRules.parse(t))
    } catch {
      toast.error("Couldn't turn that into a rule — try naming a merchant and category.")
    } finally {
      setBusy(false)
    }
  }

  async function commit() {
    if (!parsed) return
    setBusy(true)
    try {
      await financeRules.create({ ...parsed.candidate, apply_to_existing: true })
      toast.success(`Rule created — ${parsed.preview_count} transactions categorized.`)
      setText('')
      setParsed(null)
      onCreated()
    } catch {
      toast.error('Could not create the rule.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mb-5 rounded-md border border-border bg-surface px-4 py-3">
      <div className="text-sm font-medium text-text mb-2">Make a rule in plain English</div>
      <div className="flex gap-2">
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Always categorize Whole Foods as Groceries unless over $200"
          className="flex-1 rounded-md border border-border bg-surface px-3 py-2 text-sm text-text placeholder:text-text-muted focus:outline-none focus:border-primary"
          data-testid="nl-rule-input"
        />
        <button
          type="button"
          onClick={preview}
          disabled={busy || !text.trim()}
          className="rounded-md border border-border px-3 py-2 text-sm text-text hover:border-primary disabled:opacity-50"
        >
          Preview
        </button>
      </div>
      {parsed && (
        <div className="mt-2 flex items-center justify-between gap-3 text-sm" data-testid="nl-rule-preview">
          <span className="text-text-muted">
            {parsed.merchant_key} → <span className="text-text">{parsed.category_name}</span> ·{' '}
            affects <span className="text-text">{parsed.preview_count}</span> transactions
          </span>
          <button
            type="button"
            onClick={commit}
            disabled={busy}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-on-primary disabled:opacity-50"
          >
            Create rule
          </button>
        </div>
      )}
    </div>
  )
}

export default function InsightsPage() {
  const [status, setStatus] = useState<InsightStatus>('active')
  const [items, setItems] = useState<Insight[]>([])
  const [loading, setLoading] = useState(true)
  const [categories, setCategories] = useState<CategoryOption[]>([])
  const [ruleFor, setRuleFor] = useState<number | null>(null)  // insight id whose rule picker is open

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

  async function dismissAll() {
    const ok = await confirm({
      title: 'Dismiss all insights',
      message: `Dismiss all ${items.length} active insight${items.length === 1 ? '' : 's'}?`,
      confirmLabel: 'Dismiss all',
    })
    if (!ok) return
    try {
      const n = await financeInsights.dismissAll()
      toast.success(`Dismissed ${n} insight${n === 1 ? '' : 's'}.`)
      await load()
    } catch {
      toast.error('Could not dismiss insights.')
    }
  }

  async function openRulePicker(insightId: number) {
    if (categories.length === 0) {
      try {
        setCategories(await financeReview.getCategories())
      } catch {
        toast.error('Could not load categories.')
        return
      }
    }
    setRuleFor((cur) => (cur === insightId ? null : insightId))
  }

  // Insight → rule (R2.6): "always categorize {merchant} as {category}".
  async function createRuleForMerchant(insight: Insight, categoryId: number) {
    try {
      await financeRules.create({
        category_id: categoryId,
        merchant_key: insight.merchant_key,
        apply_to_existing: true,
      })
      await financeInsights.action(insight.id)
      toast.success(`Rule created for ${insight.merchant_key}.`)
      setRuleFor(null)
      await load()
    } catch {
      toast.error('Could not create the rule.')
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      <h1 className="text-lg font-semibold text-text mb-1">Insights</h1>
      <p className="text-sm text-text-muted mb-4">
        Proactive findings from your spending — duplicate charges, price hikes, forgotten trials,
        unusual activity. Ranked by dollar impact.
      </p>

      <NlRuleComposer onCreated={load} />

      <div className="flex items-center gap-1 mb-4">
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
        {status === 'active' && items.length > 0 && (
          <button
            type="button"
            onClick={dismissAll}
            className="ml-auto rounded-md border border-border px-3 py-1 text-xs font-medium text-text-muted hover:text-text hover:border-primary"
            data-testid="dismiss-all"
          >
            Dismiss all
          </button>
        )}
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
                <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                  {Object.entries(it.figures).map(([k, v]) => (
                    <div key={k} className="flex items-baseline gap-1.5 text-xs">
                      <dt className="text-text-muted capitalize">{k.replace(/_/g, ' ')}</dt>
                      <dd className="font-medium text-text">{formatFigure(v)}</dd>
                    </div>
                  ))}
                </dl>
              )}

              <div className="mt-2 flex gap-2">
                {it.status === 'active' ? (
                  <>
                    {it.merchant_key && !it.merchant_key.includes(':') && (
                      <button
                        type="button"
                        onClick={() => openRulePicker(it.id)}
                        className="rounded border border-border px-2 py-1 text-xs text-text hover:border-primary"
                      >
                        Always categorize {it.merchant_key}…
                      </button>
                    )}
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

              {ruleFor === it.id && (
                <div className="mt-2 flex items-center gap-2" data-testid="insight-rule-picker">
                  <span className="text-xs text-text-muted">Categorize {it.merchant_key} as</span>
                  <select
                    defaultValue=""
                    onChange={(e) => e.target.value && createRuleForMerchant(it, Number(e.target.value))}
                    className="rounded border border-border bg-surface px-2 py-1 text-xs text-text"
                  >
                    <option value="" disabled>
                      Pick a category…
                    </option>
                    {categories.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
