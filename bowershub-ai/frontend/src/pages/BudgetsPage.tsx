/**
 * BudgetsPage — per-category Budgeted / Spent / Remaining for a month (R3.4).
 * Actuals are allocation-aware (split children count toward their category).
 * Reuses the budgetTone helper for ok/warn/over coloring. Typed — no `any`.
 */
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { budgetTone, type BudgetTone } from '../lib/budget'
import { toast } from '../stores/toast'
import { financeBudgets, type BudgetActual } from '../services/financeBudgets'

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}

function errorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? 'Something went wrong'
}

const TONE_COLOR: Record<BudgetTone, string> = { ok: '#4a4', warn: '#c84', over: '#c44' }

function thisMonthStart(): string {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}

export default function BudgetsPage() {
  const navigate = useNavigate()
  const [month] = useState(thisMonthStart())
  const [rows, setRows] = useState<BudgetActual[]>([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await financeBudgets.getActual(month))
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [month])

  useEffect(() => { void load() }, [load])

  const edit = async (categoryId: number, raw: string) => {
    const limit = Number(raw)
    if (Number.isNaN(limit) || limit < 0) { toast.error('Enter a non-negative number'); return }
    try {
      await financeBudgets.setBudget(categoryId, month, limit)
      toast.success('Budget saved')
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }

  return (
    <div className="max-w-[820px] mx-auto p-4">
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-bold text-text">Budgets — {month.slice(0, 7)}</h1>
        <button onClick={() => navigate('/dashboard')} className="text-xs text-text-muted hover:text-text">← Dashboard</button>
      </div>

      {loading ? <p className="text-text-muted">Loading…</p> : rows.length === 0 ? (
        <p data-testid="empty" className="text-text-muted">No budgets or spending this month yet.</p>
      ) : (
        <ul className="list-none p-0 flex flex-col gap-1.5">
          {rows.map((r) => {
            const tone = r.budgeted ? budgetTone(r.actual, r.budgeted) : 'ok'
            return (
              <li
                key={r.category_id}
                data-testid="budget-row"
                className="flex flex-wrap items-center gap-x-3 gap-y-1 p-2.5 rounded-lg border border-border"
              >
                <div className="flex-1 min-w-[8rem] font-semibold text-text break-words">{r.category}</div>
                <div className="min-w-[90px] text-right font-medium" data-testid={`tone-${tone}`} style={{ color: TONE_COLOR[tone] }}>
                  {money(r.actual)}
                </div>
                <div className="min-w-[70px] text-right text-text-muted">
                  / {r.budgeted ? money(r.budgeted) : '—'}
                </div>
                <div className="min-w-[90px] text-right text-text-muted">
                  {r.remaining != null ? `${money(r.remaining)} left` : ''}
                </div>
                <input
                  aria-label={`Budget for ${r.category}`}
                  placeholder="set $"
                  defaultValue={r.budgeted || ''}
                  className="w-20 text-xs rounded border border-border bg-surface px-2 py-1 text-text"
                  onBlur={(e) => { if (e.target.value !== String(r.budgeted || '')) edit(r.category_id, e.target.value) }}
                />
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
