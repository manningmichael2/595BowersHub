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
    <div style={{ padding: 24, maxWidth: 820, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Budgets — {month.slice(0, 7)}</h1>
        <button onClick={() => navigate('/dashboard')} style={{ fontSize: 13 }}>← Dashboard</button>
      </div>

      {loading ? <p>Loading…</p> : rows.length === 0 ? (
        <p data-testid="empty">No budgets or spending this month yet.</p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {rows.map((r) => {
            const tone = r.budgeted ? budgetTone(r.actual, r.budgeted) : 'ok'
            return (
              <li key={r.category_id} data-testid="budget-row" style={{
                display: 'flex', gap: 12, alignItems: 'center', padding: 10,
                border: '1px solid var(--color-border, #333)', borderRadius: 8,
              }}>
                <div style={{ flex: 1, fontWeight: 600 }}>{r.category}</div>
                <div style={{ minWidth: 90, textAlign: 'right', color: TONE_COLOR[tone] }} data-testid={`tone-${tone}`}>
                  {money(r.actual)}
                </div>
                <div style={{ minWidth: 70, textAlign: 'right', color: 'var(--color-text-muted)' }}>
                  / {r.budgeted ? money(r.budgeted) : '—'}
                </div>
                <div style={{ minWidth: 90, textAlign: 'right' }}>
                  {r.remaining != null ? `${money(r.remaining)} left` : ''}
                </div>
                <input aria-label={`Budget for ${r.category}`} placeholder="set $"
                  defaultValue={r.budgeted || ''} style={{ width: 80, fontSize: 12 }}
                  onBlur={(e) => { if (e.target.value !== String(r.budgeted || '')) edit(r.category_id, e.target.value) }} />
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
