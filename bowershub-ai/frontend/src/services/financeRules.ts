/**
 * Typed client for NL→rule parse + commit (routers/finance_qa.py + finance_review.py).
 *
 * parse() is read-only (validated candidate + affected-count preview); create()
 * is the existing require_admin POST /user-rules commit.
 */
import { api } from './api'

export interface RuleCandidate {
  priority: number
  category_id: number
  merchant_key: string | null
  description_regex: string | null
  amount_min: number | null
  amount_max: number | null
  account_id: string | null
  is_active: boolean
}

export interface ParsedRule {
  candidate: RuleCandidate
  category_name: string
  merchant_key: string
  preview_count: number
}

export const financeRules = {
  async parse(text: string): Promise<ParsedRule> {
    const { data } = await api.post('/api/finance/rules/parse', { text })
    return data as ParsedRule
  },
  async create(payload: Partial<RuleCandidate> & { category_id: number; apply_to_existing?: boolean }): Promise<void> {
    await api.post('/api/finance/user-rules', { is_active: true, ...payload })
  },
}
