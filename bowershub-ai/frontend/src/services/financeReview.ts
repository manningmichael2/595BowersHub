/**
 * Typed client for the Finance Review API (routers/finance_review.py).
 *
 * Strict TS types mirror the Pydantic request/response models 1:1 — no `any`
 * at the boundary (R4.4/C6). All calls go through the shared `api` client (auth
 * injection + 401 refresh + toast on session expiry).
 */
import { api } from './api'

export interface ReviewQueueItem {
  id: string
  description: string | null
  amount: number
  posted_date: string | null
  account_id: string | null
  merchant_key: string | null
  predicted_category_id: number | null
  predicted_category_name: string | null
  confidence: number | null
  tier: string | null
  transfer_suspected: boolean
  rationale: Record<string, unknown> | null
}

export interface ReviewQueueResponse {
  items: ReviewQueueItem[]
  count: number
}

export interface CategoryOption {
  id: number
  name: string
  parent_id: number | null
}

export interface RecurringCharge {
  merchant_key: string
  occurrences: number
  avg_amount: number
  avg_interval_days: number | null
  last_seen: string | null
}

export interface UserRule {
  id: number | null
  priority: number
  category_id: number
  merchant_key: string | null
  description_regex: string | null
  amount_min: number | null
  amount_max: number | null
  account_id: string | null
  is_active: boolean
}

export interface ApplyMerchantResult {
  merchant_key: string
  updated: number
  rule_id: number | null
}

export const financeReview = {
  async getQueue(limit = 100, offset = 0): Promise<ReviewQueueResponse> {
    const { data } = await api.get(`/api/finance/review-queue?limit=${limit}&offset=${offset}`)
    return data as ReviewQueueResponse
  },

  async getCategories(): Promise<CategoryOption[]> {
    const { data } = await api.get('/api/finance/categories')
    return data as CategoryOption[]
  },

  async getRecurring(): Promise<RecurringCharge[]> {
    const { data } = await api.get('/api/finance/recurring')
    return (data as { charges: RecurringCharge[] }).charges
  },

  async categorize(transactionId: string, categoryId: number, learn = true): Promise<void> {
    await api.post(`/api/finance/transactions/${encodeURIComponent(transactionId)}/categorize`, {
      category_id: categoryId,
      learn,
    })
  },

  async bulkCategorize(transactionIds: string[], categoryId: number, learn = true): Promise<number> {
    const { data } = await api.post('/api/finance/transactions/bulk-categorize', {
      transaction_ids: transactionIds,
      category_id: categoryId,
      learn,
    })
    return (data as { updated: number }).updated
  },

  async applyToMerchant(
    merchantKey: string,
    categoryId: number,
    opts: { setPrior?: boolean; makeRule?: boolean } = {},
  ): Promise<ApplyMerchantResult> {
    const { data } = await api.post(
      `/api/finance/merchants/${encodeURIComponent(merchantKey)}/apply-category`,
      { category_id: categoryId, set_prior: opts.setPrior ?? true, make_rule: opts.makeRule ?? false },
    )
    return data as ApplyMerchantResult
  },

  async splitTransaction(
    transactionId: string,
    allocations: { category_id: number | null; amount: number }[],
  ): Promise<void> {
    await api.post(`/api/finance/transactions/${encodeURIComponent(transactionId)}/split`, { allocations })
  },

  async unsplitTransaction(transactionId: string): Promise<void> {
    await api.post(`/api/finance/transactions/${encodeURIComponent(transactionId)}/unsplit`)
  },
}
