/**
 * FinanceReviewPage — the dedicated Finance Review surface (R4.1, R1.6).
 *
 * Replaces the chat-only `fill:` tool with a real review queue:
 *   - queue list: merchant logo (graceful, R1.6), description, amount, the
 *     predicted category + confidence + a rationale chip (tier / why) — R4.1.
 *   - multi-select bulk-apply to one category (R4.2).
 *   - per-row inline correct, with "apply to all from this merchant" (R3.3/R4.3).
 *   - a recurring sub-view (R4.5).
 *
 * Strictly typed against the Pydantic models via `services/financeReview` — no
 * `any` at the boundary. Errors surface via the global toast.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import MerchantLogo from '../components/MerchantLogo'
import { toast } from '../stores/toast'
import {
  financeReview,
  type CategoryOption,
  type RecurringCharge,
  type ReviewQueueItem,
} from '../services/financeReview'

type Tab = 'queue' | 'recurring'

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}

function confidencePct(c: number | null): string {
  return c == null ? '—' : `${Math.round(c * 100)}%`
}

function errorMessage(e: unknown): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return detail ?? 'Something went wrong'
}

export default function FinanceReviewPage() {
  const navigate = useNavigate()
  const [tab, setTab] = useState<Tab>('queue')
  const [items, setItems] = useState<ReviewQueueItem[]>([])
  const [categories, setCategories] = useState<CategoryOption[]>([])
  const [recurring, setRecurring] = useState<RecurringCharge[]>([])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkCategory, setBulkCategory] = useState<number | ''>('')
  const [loading, setLoading] = useState(true)

  const catName = useMemo(() => {
    const m = new Map<number, string>()
    categories.forEach((c) => m.set(c.id, c.name))
    return m
  }, [categories])

  const loadQueue = useCallback(async () => {
    setLoading(true)
    try {
      const [q, cats] = await Promise.all([financeReview.getQueue(), financeReview.getCategories()])
      setItems(q.items)
      setCategories(cats)
      setSelected(new Set())
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadRecurring = useCallback(async () => {
    try {
      setRecurring(await financeReview.getRecurring())
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }, [])

  useEffect(() => {
    void loadQueue()
  }, [loadQueue])

  useEffect(() => {
    if (tab === 'recurring') void loadRecurring()
  }, [tab, loadRecurring])

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const correct = async (item: ReviewQueueItem, categoryId: number, applyToMerchant: boolean) => {
    try {
      if (applyToMerchant && item.merchant_key) {
        const res = await financeReview.applyToMerchant(item.merchant_key, categoryId, { setPrior: true })
        toast.success(`Applied to ${res.updated} ${item.merchant_key} transaction(s)`)
      } else {
        await financeReview.categorize(item.id, categoryId)
        toast.success('Categorized')
      }
      await loadQueue()
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  const applyBulk = async () => {
    if (bulkCategory === '' || selected.size === 0) return
    try {
      const n = await financeReview.bulkCategorize([...selected], bulkCategory)
      toast.success(`Categorized ${n} transaction(s)`)
      setBulkCategory('')
      await loadQueue()
    } catch (e) {
      toast.error(errorMessage(e))
    }
  }

  return (
    <div style={{ padding: 24, maxWidth: 980, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h1 style={{ fontSize: 22, fontWeight: 700 }}>Finance Review</h1>
        <button onClick={() => navigate('/dashboard')} style={{ fontSize: 13 }}>← Dashboard</button>
      </div>

      <div role="tablist" style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
        <button role="tab" aria-selected={tab === 'queue'} onClick={() => setTab('queue')}>
          Review Queue
        </button>
        <button role="tab" aria-selected={tab === 'recurring'} onClick={() => setTab('recurring')}>
          Recurring
        </button>
      </div>

      {tab === 'queue' && (
        <>
          {selected.size > 0 && (
            <div data-testid="bulk-bar" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 12 }}>
              <span>{selected.size} selected</span>
              <select
                aria-label="Bulk category"
                value={bulkCategory}
                onChange={(e) => setBulkCategory(e.target.value === '' ? '' : Number(e.target.value))}
              >
                <option value="">Choose category…</option>
                {categories.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
              <button onClick={applyBulk} disabled={bulkCategory === ''}>Apply to selected</button>
            </div>
          )}

          {loading ? (
            <p>Loading…</p>
          ) : items.length === 0 ? (
            <p data-testid="empty-queue">Nothing to review — the queue is clear. 🎉</p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: 8 }}>
              {items.map((item) => (
                <QueueRow
                  key={item.id}
                  item={item}
                  categories={categories}
                  categoryName={(id) => catName.get(id) ?? `#${id}`}
                  checked={selected.has(item.id)}
                  onToggle={() => toggleSelect(item.id)}
                  onCorrect={correct}
                />
              ))}
            </ul>
          )}
        </>
      )}

      {tab === 'recurring' && (
        <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {recurring.length === 0 ? (
            <p data-testid="empty-recurring">No recurring charges detected.</p>
          ) : (
            recurring.map((r) => (
              <li key={r.merchant_key} style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                <MerchantLogo merchantKey={r.merchant_key} />
                <span style={{ fontWeight: 600 }}>{r.merchant_key}</span>
                <span>{r.occurrences}×</span>
                <span>{money(r.avg_amount)}</span>
                {r.avg_interval_days != null && <span>~{Math.round(r.avg_interval_days)}d</span>}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}

interface RowProps {
  item: ReviewQueueItem
  categories: CategoryOption[]
  categoryName: (id: number) => string
  checked: boolean
  onToggle: () => void
  onCorrect: (item: ReviewQueueItem, categoryId: number, applyToMerchant: boolean) => void
}

function QueueRow({ item, categories, categoryName, checked, onToggle, onCorrect }: RowProps) {
  const [choice, setChoice] = useState<number | ''>('')
  const [applyMerchant, setApplyMerchant] = useState(false)

  return (
    <li
      data-testid="queue-row"
      style={{
        display: 'flex', gap: 12, alignItems: 'center', padding: 10,
        border: '1px solid var(--color-border, #333)', borderRadius: 8,
      }}
    >
      <input type="checkbox" checked={checked} onChange={onToggle} aria-label={`Select ${item.description ?? item.id}`} />
      <MerchantLogo merchantKey={item.merchant_key} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {item.description ?? item.merchant_key ?? '(no description)'}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4, fontSize: 12 }}>
          {item.transfer_suspected && (
            <span data-testid="transfer-chip" style={chip('#7a4')}>transfer?</span>
          )}
          {item.predicted_category_id != null && (
            <span data-testid="prediction-chip" style={chip('#468')}>
              {item.predicted_category_name ?? categoryName(item.predicted_category_id)} · {confidencePct(item.confidence)}
            </span>
          )}
          {item.tier && <span style={chip('#555')}>{item.tier}</span>}
        </div>
      </div>
      <div style={{ textAlign: 'right', minWidth: 84 }}>{money(item.amount)}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
        <select
          aria-label={`Category for ${item.description ?? item.id}`}
          value={choice}
          onChange={(e) => setChoice(e.target.value === '' ? '' : Number(e.target.value))}
        >
          <option value="">Correct…</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {item.merchant_key && (
          <label style={{ fontSize: 11 }}>
            <input type="checkbox" checked={applyMerchant} onChange={(e) => setApplyMerchant(e.target.checked)} />{' '}
            all {item.merchant_key}
          </label>
        )}
        <button
          disabled={choice === ''}
          onClick={() => choice !== '' && onCorrect(item, choice, applyMerchant)}
        >
          Save
        </button>
      </div>
    </li>
  )
}

function chip(bg: string): React.CSSProperties {
  return { background: bg, color: '#fff', borderRadius: 10, padding: '2px 8px', whiteSpace: 'nowrap' }
}
