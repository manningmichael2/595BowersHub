/**
 * Typed client for the Finance Accounting API (routers/finance_accounting.py).
 * Strict types mirror the Pydantic models 1:1 — no `any` at the boundary. All
 * calls go through the shared `api` client (auth + 401 refresh + toast).
 */
import { api } from './api'

export interface AccountBalance {
  id: string
  name: string
  org: string | null
  account_type: string | null
  balance: number
  as_of: string | null
  classification: 'asset' | 'liability' | 'needs_type'
  included: boolean
  stale: boolean
}

export interface NetWorth {
  net_worth: number
  assets: number
  liabilities: number
  accounts: AccountBalance[]
}

export interface NetWorthPoint {
  date: string
  net_worth: number
}

export interface AccountStatus {
  account_id: string
  synced_balance: number | null
  as_of: string | null
  reconciled_through_date: string | null
  cleared_tally: number
  reconcile_tolerance: number
}

export interface ReconcileResult {
  reconciliation_id: number
  account_id: string
  statement_balance: number
  synced_balance: number | null
  delta: number | null
  in_sync: boolean
}

export const ACCOUNT_TYPES = ['checking', 'savings', 'credit_card', 'loan', 'mortgage', 'brokerage'] as const

export const financeAccounting = {
  async getNetWorth(): Promise<NetWorth> {
    const { data } = await api.get('/api/finance/net-worth')
    return data as NetWorth
  },

  async getHistory(days = 365): Promise<NetWorthPoint[]> {
    const { data } = await api.get(`/api/finance/net-worth/history?days=${days}`)
    return (data as { series: NetWorthPoint[] }).series
  },

  async getAccountStatus(accountId: string): Promise<AccountStatus> {
    const { data } = await api.get(`/api/finance/accounts/${encodeURIComponent(accountId)}/status`)
    return data as AccountStatus
  },

  async setAccountType(accountId: string, accountType: string): Promise<void> {
    await api.put(`/api/finance/accounts/${encodeURIComponent(accountId)}/type`, { account_type: accountType })
  },

  async reconcile(accountId: string, statementDate: string, statementBalance: number): Promise<ReconcileResult> {
    const { data } = await api.post(`/api/finance/accounts/${encodeURIComponent(accountId)}/reconcile`, {
      statement_date: statementDate,
      statement_balance: statementBalance,
    })
    return data as ReconcileResult
  },

  async link(aId: string, bId: string): Promise<void> {
    await api.post('/api/finance/transactions/link', { a_id: aId, b_id: bId })
  },

  async unlink(id: string): Promise<void> {
    await api.post('/api/finance/transactions/unlink', { id })
  },
}
