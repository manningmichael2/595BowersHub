/**
 * Typed client for the Finance Budgets API (routers/finance_budgets.py).
 * Strict types mirror the Pydantic models 1:1 — no `any` at the boundary.
 */
import { api } from './api'

export interface BudgetActual {
  category_id: number
  category: string
  budgeted: number
  actual: number
  remaining: number | null
}

export const financeBudgets = {
  async getActual(month: string): Promise<BudgetActual[]> {
    const { data } = await api.get(`/api/finance/budgets/actual?month=${month}`)
    return (data as { categories: BudgetActual[] }).categories
  },

  async setBudget(categoryId: number, month: string, limit: number): Promise<void> {
    await api.put('/api/finance/budgets', { category_id: categoryId, month, limit_amount: limit })
  },
}
