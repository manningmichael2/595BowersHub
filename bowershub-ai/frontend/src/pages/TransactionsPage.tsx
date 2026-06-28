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
import { Combobox, DateRangePicker } from '../components/ui/finance'
import { parseDate } from '@internationalized/date'
import { useIsMobile } from '../hooks/useMediaQuery'
import { financeReview, type CategoryOption } from '../services/financeReview'
import {
  financeTransactions,
  attributionHint,
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
// Shared tokenized field styling (was the inline `inputStyle`).
const INPUT_CLS = 'bg-surface text-text border border-border rounded px-2 py-1'
const POS = 'text-success'   // positive/income amounts (theme success token)

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
  const isMobile = useIsMobile()

  useEffect(() => { financeReview.getCategories().then(setCategories).catch(() => {}) }, [])

  // Searchable-combobox options for category pickers (filter + bulk).
  const categoryOptions = useMemo(
    () => categories.map((c) => ({ id: c.id, label: c.name })),
    [categories],
  )

  // Bridge the string ('YYYY-MM-DD') date state to the DateRangePicker's
  // CalendarDate range. Empty bounds ("All time") → no range selected.
  const dateRange = useMemo(() => {
    try {
      return start && end ? { start: parseDate(start), end: parseDate(end) } : null
    } catch {
      return null
    }
  }, [start, end])

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

  // Shared cell renderers so the desktop table and mobile cards stay in sync.
  const renderCategory = (t: TxnSearchResult['items'][number]) =>
    t.is_split ? (
      <span className="text-text-muted">(split)</span>
    ) : t.is_transfer ? (
      <span className="text-accent">Transfer</span>
    ) : t.is_investment ? (
      <span className="text-text-muted">Investment</span>
    ) : (
      <select
        aria-label={`Category for ${t.description ?? t.id}`}
        className={`${INPUT_CLS} text-xs`}
        value={t.category_id ?? ''}
        onChange={(e) => e.target.value && categorize(t.id, Number(e.target.value))}
      >
        <option value="">{t.category_name ? t.category_name : 'Uncategorized…'}</option>
        {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>
    )

  const renderSplitBtn = (t: TxnSearchResult['items'][number]) =>
    t.is_split ? (
      <button className="text-[11px] text-text-muted hover:text-text" onClick={() => doUnsplit(t.id)}>Unsplit</button>
    ) : !t.is_transfer && !t.is_investment ? (
      <button className="text-[11px] text-text-muted hover:text-text" onClick={() => setSplittingId((id) => (id === t.id ? null : t.id))}>Split</button>
    ) : null

  return (
    <div className="max-w-[1100px] mx-auto p-4">
      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <input className={`${INPUT_CLS} flex-1 min-w-[160px]`} placeholder="Search description / merchant…"
          value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search transactions" />
        <Combobox
          className="min-w-[180px]"
          aria-label="Filter category"
          options={categoryOptions}
          selectedKey={categoryId === '' ? null : categoryId}
          onSelectionChange={(k) => setCategoryId(k == null ? '' : Number(k))}
          placeholder="All categories"
        />
        <select className={INPUT_CLS} value={status} aria-label="Filter status"
          onChange={(e) => setStatus(e.target.value as TxnStatus)}>
          {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <button className="text-xs text-text-muted hover:text-text" onClick={() => { setQ(''); setCategoryId(''); setStart(''); setEnd(''); setStatus('all') }}>Clear</button>
      </div>

      {/* Date range: presets + custom start/end slicer */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        {DATE_PRESETS.map((preset) => {
          const [ps, pe] = preset.range()
          const active = start === ps && end === pe
          return (
            <button key={preset.label} className={`text-xs ${active ? 'font-bold text-text' : 'font-normal text-text-muted'}`}
              onClick={() => { setStart(ps); setEnd(pe) }}>{preset.label}</button>
          )
        })}
        <span className="text-text-muted text-xs">·</span>
        <DateRangePicker
          aria-label="Custom date range"
          value={dateRange}
          onChange={(range) => {
            if (range) {
              setStart(range.start.toString())
              setEnd(range.end.toString())
            } else {
              setStart('')
              setEnd('')
            }
          }}
        />
      </div>

      {/* Bulk action bar */}
      {selected.size > 0 && (
        <div data-testid="bulk-bar" className="flex flex-wrap items-center gap-2 mb-2.5">
          <span className="text-xs text-text">{selected.size} selected</span>
          <Combobox
            className="min-w-[180px]"
            aria-label="Bulk category"
            options={categoryOptions}
            selectedKey={bulkCat === '' ? null : bulkCat}
            onSelectionChange={(k) => setBulkCat(k == null ? '' : Number(k))}
            placeholder="Choose category…"
          />
          <button className="text-xs text-text-muted hover:text-text disabled:opacity-50" disabled={bulkCat === ''} onClick={applyBulk}>Apply to selected</button>
          <button className="text-xs text-text-muted hover:text-text" onClick={() => setSelected(new Set())}>Clear</button>
        </div>
      )}

      {/* Totals summary */}
      {result && (
        <div className="flex flex-wrap gap-5 mb-2.5 text-xs text-text">
          <span>Income <b className={POS}>{money(result.totals.income)}</b></span>
          <span>Spending <b className="text-danger">{money(result.totals.spending)}</b></span>
          <span>Net <b>{money(net)}</b></span>
          <span className="text-text-muted">{result.count} transactions</span>
        </div>
      )}

      <div className="flex flex-col lg:flex-row gap-4 lg:items-start">
        {/* Transactions: a table on desktop, stacked cards on mobile (R5.3) */}
        <div className="flex-1 min-w-0">
          {loading ? <p className="text-text-muted">Loading…</p> : !result || result.items.length === 0 ? (
            <p data-testid="empty" className="text-text-muted">No transactions match.</p>
          ) : isMobile ? (
            <ul className="list-none p-0 flex flex-col gap-1.5">
              {result.items.map((t) => (
                <li key={t.id} data-testid="txn-row" className="rounded-lg border border-border p-2.5">
                  <div className="flex items-start gap-2">
                    <input type="checkbox" aria-label={`Select ${t.description ?? t.id}`} className="mt-1"
                      checked={selected.has(t.id)} onChange={() => toggleSel(t.id)} />
                    <div className="flex-1 min-w-0">
                      <div className="flex justify-between gap-2">
                        <span className="font-medium text-text break-words">{t.description ?? t.merchant_key ?? '—'}</span>
                        <span className={`shrink-0 ${t.amount < 0 ? 'text-text' : POS}`}>{money(t.amount)}</span>
                      </div>
                      <div className="text-xs text-text-muted mt-0.5">
                        {t.posted_date}
                        {attributionHint(t) && <span className="ml-2">· {attributionHint(t)}</span>}
                      </div>
                      <div className="flex items-center justify-between gap-2 mt-1">
                        {renderCategory(t)}
                        {renderSplitBtn(t)}
                      </div>
                    </div>
                  </div>
                  {splittingId === t.id && (
                    <div className="mt-2">
                      <SplitEditor amount={t.amount} categories={categories}
                        onCancel={() => setSplittingId(null)} onSave={(allocs) => doSplit(t.id, allocs)} />
                    </div>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <table className="w-full border-collapse text-[13px]">
              <thead>
                <tr className="text-left text-text-muted border-b border-border">
                  <th className="p-1.5">
                    <input type="checkbox" aria-label="Select all"
                      checked={result.items.length > 0 && result.items.every((t) => selected.has(t.id))}
                      onChange={(e) => setSelected(e.target.checked ? new Set(result.items.map((t) => t.id)) : new Set())} />
                  </th>
                  <th className="p-1.5 cursor-pointer" onClick={() => toggleSort('date')}>Date{arrow('date')}</th>
                  <th className="p-1.5 cursor-pointer" onClick={() => toggleSort('description')}>Description{arrow('description')}</th>
                  <th className="p-1.5 cursor-pointer" onClick={() => toggleSort('category')}>Category{arrow('category')}</th>
                  <th className="p-1.5 cursor-pointer text-right" onClick={() => toggleSort('amount')}>Amount{arrow('amount')}</th>
                  <th className="p-1.5" />
                </tr>
              </thead>
              <tbody>
                {result.items.map((t) => (
                  <Fragment key={t.id}>
                    <tr data-testid="txn-row" className="border-b border-border">
                      <td className="p-1.5">
                        <input type="checkbox" aria-label={`Select ${t.description ?? t.id}`}
                          checked={selected.has(t.id)} onChange={() => toggleSel(t.id)} />
                      </td>
                      <td className="p-1.5 whitespace-nowrap">{t.posted_date}</td>
                      <td className="p-1.5">
                        {t.description ?? t.merchant_key ?? '—'}
                        {attributionHint(t) && (
                          <span className="block text-xs text-text-muted">{attributionHint(t)}</span>
                        )}
                      </td>
                      <td className="p-1.5">{renderCategory(t)}</td>
                      <td className={`p-1.5 text-right ${t.amount < 0 ? '' : POS}`}>{money(t.amount)}</td>
                      <td className="p-1.5 text-right whitespace-nowrap">{renderSplitBtn(t)}</td>
                    </tr>
                    {splittingId === t.id && (
                      <tr>
                        <td colSpan={6} className="px-1.5 pb-2">
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

        {/* By-category subtotals — stacks below the list on mobile */}
        {result && result.subtotals.length > 0 && (
          <div className="w-full lg:w-60 lg:shrink-0">
            <div className="text-xs font-semibold text-text-muted mb-1.5">By category</div>
            <ul className="list-none p-0 m-0 flex flex-col gap-1">
              {result.subtotals.map((s) => (
                <li key={s.category} className="flex justify-between text-xs">
                  <span className="text-text">{s.category}</span>
                  <span className={s.total < 0 ? 'text-text' : POS}>{money(s.total)}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}
