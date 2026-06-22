/**
 * Typed client for the Retirement planner API (routers/retirement.py).
 *
 * /project is reactive — send the live form state as overrides and get a fresh
 * projection (chart series + stats + disclaimer) without persisting.
 */
import { api } from './api'

export interface RetirementFields {
  current_age: number | null
  retirement_age: number | null
  current_balance: number | null
  annual_salary: number | null
  annual_contribution: number | null
  annual_expenses: number | null
  expected_return: number | null
  inflation: number | null
  withdrawal_rate: number | null
  end_age: number | null
}

export interface ProjectionPoint {
  age: number
  balance: number
}

export interface Projection {
  series?: ProjectionPoint[]
  retirement_age?: number
  retirement_balance?: number
  fire_target?: number
  surplus_or_gap?: number
  on_track?: boolean
  depletion_age?: number | null
  required_monthly_contribution?: number
  earliest_age_on_track?: number | null
  disclaimer: string
  needs_inputs?: boolean
}

export const financeRetirement = {
  async getInputs(): Promise<{ has_inputs: boolean; prefill: RetirementFields }> {
    const { data } = await api.get('/api/finance/retirement/inputs')
    return data as { has_inputs: boolean; prefill: RetirementFields }
  },
  async saveInputs(fields: RetirementFields): Promise<void> {
    await api.put('/api/finance/retirement/inputs', fields)
  },
  async project(overrides: Partial<RetirementFields>): Promise<Projection> {
    const { data } = await api.post('/api/finance/retirement/project', { overrides })
    return data as Projection
  },
}
