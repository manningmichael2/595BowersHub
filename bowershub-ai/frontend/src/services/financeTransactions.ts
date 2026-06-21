/**
 * Typed client for the transactions explorer (routers/finance_transactions.py).
 * No `any` at the boundary.
 */
import { api } from './api'

export interface TxnRow {
  id: string
  posted_date: string
  description: string | null
  merchant_key: string | null
  amount: number
  account_id: string | null
  account_name: string | null
  category_id: number | null
  category_name: string | null
  is_transfer: boolean
  is_investment: boolean
  is_split: boolean
  cleared: boolean
}

export interface Subtotal { category: string; total: number; count: number }
export interface Totals { income: number; spending: number }

export interface TxnSearchResult {
  items: TxnRow[]
  count: number
  subtotals: Subtotal[]
  totals: Totals
}

export type TxnStatus = 'all' | 'uncategorized' | 'spending' | 'income' | 'transfers'

export interface TxnQuery {
  q?: string
  category_id?: number
  month?: string          // YYYY-MM-01
  start?: string          // YYYY-MM-DD (inclusive)
  end?: string            // YYYY-MM-DD (inclusive)
  status?: TxnStatus
  sort?: 'date' | 'amount' | 'category' | 'description'
  order?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

export const financeTransactions = {
  async search(query: TxnQuery): Promise<TxnSearchResult> {
    const p = new URLSearchParams()
    if (query.q) p.set('q', query.q)
    if (query.category_id != null) p.set('category_id', String(query.category_id))
    if (query.month) p.set('month', query.month)
    if (query.start) p.set('start', query.start)
    if (query.end) p.set('end', query.end)
    if (query.status && query.status !== 'all') p.set('status', query.status)
    if (query.sort) p.set('sort', query.sort)
    if (query.order) p.set('order', query.order)
    if (query.limit != null) p.set('limit', String(query.limit))
    if (query.offset != null) p.set('offset', String(query.offset))
    const { data } = await api.get(`/api/finance/transactions?${p.toString()}`)
    return data as TxnSearchResult
  },
}
