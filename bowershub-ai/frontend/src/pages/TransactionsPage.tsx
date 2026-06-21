/**
 * TransactionsPage — the unified Monarch/Origin-style transactions explorer
 * (Finance → Transactions). Search + filter (category/month/status), sortable
 * columns, by-category subtotals + in/out totals. Allocation-aware (splits count
 * per child category; split parents shown once). Inline categorize/split folds in
 * next so this becomes the single finance transactions surface.
 */
import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { toast } from '../stores/toast'
import SplitEditor from '../components/finance/SplitEditor'
import { financeReview, type CategoryOption } from '../services/financeReview'
import {
  financeTransactions,
  type TxnQuery,
  type TxnSearchResult,
  type TxnStatus,
} from '../services/financeTransactions'

function money(n: number): string {
  return new Intl.NumberFormat(undefined, { style: 'currency', currency: 'USD' }).format(n)
}
function errorMessage(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail
  return d ?? 'Something went wrong'
}

const STATUSES: TxnStatus[] = ['all', 'uncategorized', 'spending', 'income', 'transfers']
const inputStyle: React.CSSProperties = {
  background: 'var(--color-surface)', color: 'var(--color-text)',
  border: '1px solid var(--color-border, #374151)', borderRadius: 6, padding: '4px 8px',
}

function fmtDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function daysAgo(n: number): string { const d = new Date(); d.setDate(d.getDate() - n); return fmtDate(d) }
function yearStart(): string { return `${new Date().getFullYear()}-01-01` }
function todayStr(): string { return fmtDate(new Date()) }

const DATE_PRESETS: { label: string; range: () => [string, string] }[] = [
  { label: 'This year', range: () => [yearStart(), todayStr()] },
  { label: 'Last 30 days', range: () => [daysAgo(30), todayStr()] },
  { label: 'Last 7 days', range: () => [daysAgo(7), todayStr()] },
  { label: 'All time', range: () => ['', ''] },
]

export default function TransactionsPage() {
  const [categories, setCategories] = useState<CategoryOption[]>([])
  const [result, setResult] = useState<TxnSearchResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [categoryId, setCategoryId] = useState<number | ''>('')
  const [start, setStart] = useState(yearStart())   // default: this year to date
  const [end, setEnd] = useState(todayStr())
  const [status, setStatus] = useState<TxnStatus>('all')
  const [sort, setSort] = useState<NonNullable<TxnQuery['sort']>>('date')
  const [order, setOrder] = useState<NonNullable<TxnQuery['order']>>('desc')
  const [splittingId, setSplittingId] = useState<string | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [bulkCat, setBulkCat] = useState<number | ''>('')

  useEffect(() => { financeReview.getCategories().then(setCategories).catch(() => {}) }, [])

  const load = useCallback(async () => {
    setLoading(true)
    try {
      setResult(await financeTransactions.search({
        q: q || undefined,
        category_id: categoryId === '' ? undefined : categoryId,
        start: start || undefined,
        end: end || undefined,
        status, sort, order, limit: 200,
      }))
    } catch (e) {
      toast.error(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [q, categoryId, start, end, status, sort, order])

  useEffect(() => {
    const t = setTimeout(() => void load(), 250)  // debounce text input
    return () => clearTimeout(t)
  }, [load])

  const categorize = async (id: string, categoryId: number) => {
    try {
      await financeReview.categorize(id, categoryId)
      toast.success('Categorized')
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }
  const doSplit = async (id: string, allocations: { category_id: number | null; amount: number }[]) => {
    try {
      await financeReview.splitTransaction(id, allocations)
      toast.success(`Split into ${allocations.length}`)
      setSplittingId(null)
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }
  const doUnsplit = async (id: string) => {
    try {
      await financeReview.unsplitTransaction(id)
      toast.success('Unsplit')
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }
  const toggleSel = (id: string) => setSelected((prev) => {
    const next = new Set(prev)
    next.has(id) ? next.delete(id) : next.add(id)
    return next
  })
  const applyBulk = async () => {
    if (bulkCat === '' || selected.size === 0) return
    try {
      const n = await financeReview.bulkCategorize([...selected], bulkCat)
      toast.success(`Categorized ${n}`)
      setBulkCat(''); setSelected(new Set())
      await load()
    } catch (e) { toast.error(errorMessage(e)) }
  }

  const toggleSort = (col: NonNullable<TxnQuery['sort']>) => {
    if (sort === col) setOrder((o) => (o === 'asc' ? 'desc' : 'asc'))
    else { setSort(col); setOrder('desc') }
  }
  const arrow = (col: string) => (sort === col ? (order === 'asc' ? ' ▲' : ' ▼') : '')

  const net = useMemo(() => result ? result.totals.income - result.totals.spending : 0, [result])

  return (
    <div style={{ padding: 16, maxWidth: 1100, margin: '0 auto' }}>
      {/* Filter bar */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        <input style={{ ...inputStyle, flex: 1, minWidth: 160 }} placeholder="Search description / merchant…"
          value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search transactions" />
        <select style={inputStyle} value={categoryId} aria-label="Filter category"
          onChange={(e) => setCategoryId(e.target.value === '' ? '' : Number(e.target.value))}>
          <option value="">All categories</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
        <select style={inputStyle} value={status} aria-label="Filter status"
          onChange={(e) => setStatus(e.target.value as TxnStatus)}>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button style={{ fontSize: 12 }} onClick={() => { setQ(''); setCategoryId(''); setStart(''); setEnd(''); setStatus('all') }}>Clear</button>
      </div>

      {/* Date range: presets + custom start/end slicer */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginBottom: 12 }}>
        {DATE_PRESETS.map((preset) => {
          const [ps, pe] = preset.range()
          const active = start === ps && end === pe
          return (
            <button key={preset.label} style={{ fontSize: 12, fontWeight: active ? 700 : 400, opacity: active ? 1 : 0.7 }}
              onClick={() => { setStart(ps); setEnd(pe) }}>{preset.label}</button>
          )
        })}
        <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>·</span>
        <input style={{ ...inputStyle, fontSize: 12 }} type="date" aria-label="Start date"
          value={start} max={end || undefined} onChange={(e) => setStart(e.target.value)} />
        <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>to</span>
        <input style={{ ...inputStyle, fontSize: 12 }} type="date" aria-label="End date"
          value={end} min={start || undefined} onChange={(e) => setEnd(e.target.value)} />
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div data-testid="bulk-bar" style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
          <span style={{ fontSize: 13 }}>{selected.size} selected</span>
          <select style={{ ...inputStyle, fontSize: 12 }} aria-label="Bulk category" value={bulkCat}
            onChange={(e) => setBulkCat(e.target.value === '' ? '' : Number(e.target.value))}>
            <option value="">Choose category…</option>
            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          <button style={{ fontSize: 12 }} disabled={bulkCat === ''} onClick={applyBulk}>Apply to selected</button>
          <button style={{ fontSize: 12 }} onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      {/* Totals summary */}
      {result && (
        <div style={{ display: 'flex', gap: 20, marginBottom: 10, fontSize: 13 }}>
          <span>Income <b style={{ color: '#4a4' }}>{money(result.totals.income)}</b></span>
          <span>Spending <b style={{ color: '#c66' }}>{money(result.totals.spending)}</b></span>
          <span>Net <b>{money(net)}</b></span>
          <span style={{ color: 'var(--color-text-muted)' }}>{result.count} transactions</span>
        </div>
      )}

      <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start' }}>
        {/* Table */}
        <div style={{ flex: 1, minWidth: 0 }}>
          {loading ? <p>Loading…</p> : !result || result.items.length === 0 ? (
            <p data-testid="empty">No transactions match.</p>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ textAlign: 'left', color: 'var(--color-text-muted)', borderBottom: '1px solid var(--color-border,#333)' }}>
                  <th style={{ padding: 6 }}>
                    <input type="checkbox" aria-label="Select all"
                      checked={result.items.length > 0 && result.items.every((t) => selected.has(t.id))}
                      onChange={(e) => setSelected(e.target.checked ? new Set(result.items.map((t) => t.id)) : new Set())} />
                  </th>
                  <th style={{ cursor: 'pointer', padding: 6 }} onClick={() => toggleSort('date')}>Date{arrow('date')}</th>
                  <th style={{ cursor: 'pointer', padding: 6 }} onClick={() => toggleSort('description')}>Description{arrow('description')}</th>
                  <th style={{ cursor: 'pointer', padding: 6 }} onClick={() => toggleSort('category')}>Category{arrow('category')}</th>
                  <th style={{ cursor: 'pointer', padding: 6, textAlign: 'right' }} onClick={() => toggleSort('amount')}>Amount{arrow('amount')}</th>
                  <th style={{ padding: 6 }} />
                </tr>
              </thead>
              <tbody>
                {result.items.map((t) => (
                  <Fragment key={t.id}>
                    <tr data-testid="txn-row" style={{ borderBottom: '1px solid var(--color-border,#222)' }}>
                      <td style={{ padding: 6 }}>
                        <input type="checkbox" aria-label={`Select ${t.description ?? t.id}`}
                          checked={selected.has(t.id)} onChange={() => toggleSel(t.id)} />
                      </td>
                      <td style={{ padding: 6, whiteSpace: 'nowrap' }}>{t.posted_date}</td>
                      <td style={{ padding: 6 }}>{t.description ?? t.merchant_key ?? '—'}</td>
                      <td style={{ padding: 6 }}>
                        {t.is_split ? (
                          <span style={{ color: 'var(--color-text-muted)' }}>(split)</span>
                        ) : t.is_transfer ? (
                          <span style={{ color: '#7a4' }}>Transfer</span>
                        ) : t.is_investment ? (
                          <span style={{ color: 'var(--color-text-muted)' }}>Investment</span>
                        ) : (
                          <select aria-label={`Category for ${t.description ?? t.id}`} style={{ ...inputStyle, fontSize: 12 }}
                            value={t.category_id ?? ''}
                            onChange={(e) => e.target.value && categorize(t.id, Number(e.target.value))}>
                            <option value="">{t.category_name ? t.category_name : 'Uncategorized…'}</option>
                            {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
                          </select>
                        )}
                      </td>
                      <td style={{ padding: 6, textAlign: 'right', color: t.amount < 0 ? 'inherit' : '#4a4' }}>{money(t.amount)}</td>
                      <td style={{ padding: 6, textAlign: 'right', whiteSpace: 'nowrap' }}>
                        {t.is_split ? (
                          <button style={{ fontSize: 11 }} onClick={() => doUnsplit(t.id)}>Unsplit</button>
                        ) : !t.is_transfer && !t.is_investment ? (
                          <button style={{ fontSize: 11 }} onClick={() => setSplittingId((id) => (id === t.id ? null : t.id))}>Split</button>
                        ) : null}
                      </td>
                    </tr>
                    {splittingId === t.id && (
                      <tr>
                        <td colSpan={6} style={{ padding: '0 6px 8px' }}>
                          <SplitEditor amount={t.amount} categories={categories}
                            onCancel={() => setSplittingId(null)}
                            onSave={(allocs) => doSplit(t.id, allocs)} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* By-category subtotals */}
        {result && result.subtotals.length > 0 && (
          <div style={{ width: 240, flexShrink: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)', marginBottom: 6 }}>By category</div>
            <ul style={{ listStyle: 'none', padding: 0, margin: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {result.subtotals.map((s) => (
                <li key={s.category} style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
                  <span>{s.category}</span>
                  <span style={{ color: s.total < 0 ? 'inherit' : '#4a4' }}>{money(s.total)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
