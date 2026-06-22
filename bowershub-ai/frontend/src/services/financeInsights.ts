/**
 * Typed client for the Finance Insights API (routers/finance_insights.py).
 *
 * Strict TS types mirror the serialized rows 1:1 — no `any` at the boundary.
 */
import { api } from './api'

export type InsightStatus = 'active' | 'dismissed' | 'actioned'

export interface Insight {
  id: number
  insight_type: string
  merchant_key: string
  period: string
  status: InsightStatus
  dollar_impact: number
  figures: Record<string, unknown>
  reason: string | null
  created_at: string | null
}

export const financeInsights = {
  async list(status: InsightStatus | 'all' = 'active'): Promise<Insight[]> {
    const { data } = await api.get(`/api/finance/insights?status=${status}`)
    return (data as { insights: Insight[] }).insights
  },
  async dismiss(id: number): Promise<void> {
    await api.post(`/api/finance/insights/${id}/dismiss`)
  },
  async reopen(id: number): Promise<void> {
    await api.post(`/api/finance/insights/${id}/reopen`)
  },
  async action(id: number): Promise<void> {
    await api.post(`/api/finance/insights/${id}/action`)
  },
}
