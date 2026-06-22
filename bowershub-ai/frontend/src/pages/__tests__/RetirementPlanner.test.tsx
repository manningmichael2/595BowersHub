/**
 * Component tests for RetirementPlanner (ai-finance-insights Task 16 / R4.6-R4.8).
 *   1. Renders chart + stats + disclaimer from a projection.
 *   2. Editing retirement age re-projects (reactive recompute).
 *   3. needs_inputs → setup state, no fabricated projection.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../../services/financeRetirement', () => ({
  financeRetirement: { getInputs: vi.fn(), saveInputs: vi.fn(), project: vi.fn() },
}))
vi.mock('../../stores/toast', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

import RetirementPlanner from '../RetirementPlanner'
import { financeRetirement, type Projection } from '../../services/financeRetirement'

const PREFILL = {
  current_age: 40, retirement_age: 65, current_balance: 100000, annual_salary: 90000,
  annual_contribution: 12000, annual_expenses: 40000, expected_return: 0.07,
  inflation: 0.03, withdrawal_rate: 0.04, end_age: 95,
}

const PROJECTION: Projection = {
  series: [{ age: 40, balance: 100000 }, { age: 65, balance: 900000 }, { age: 95, balance: 200000 }],
  retirement_age: 65, retirement_balance: 900000, fire_target: 1000000,
  surplus_or_gap: -100000, on_track: false, depletion_age: null,
  required_monthly_contribution: 500, earliest_age_on_track: null,
  disclaimer: 'These projections are estimates, not advice.',
}

afterEach(cleanup)

describe('RetirementPlanner', () => {
  it('renders chart, stats, and disclaimer from a projection', async () => {
    vi.mocked(financeRetirement.getInputs).mockResolvedValue({ has_inputs: true, prefill: PREFILL })
    vi.mocked(financeRetirement.project).mockResolvedValue(PROJECTION)
    render(<RetirementPlanner />)

    await waitFor(() => expect(screen.getByTestId('ret-projection')).toBeTruthy())
    expect(screen.getByTestId('ret-chart')).toBeTruthy()
    expect(screen.getByTestId('ret-disclaimer')).toBeTruthy()
    expect(screen.getByText('$1,000,000')).toBeTruthy()  // FIRE target
  })

  it('editing retirement age re-projects (reactive)', async () => {
    vi.mocked(financeRetirement.getInputs).mockResolvedValue({ has_inputs: true, prefill: PREFILL })
    vi.mocked(financeRetirement.project).mockResolvedValue(PROJECTION)
    render(<RetirementPlanner />)
    await waitFor(() => expect(financeRetirement.project).toHaveBeenCalled())

    const calls = vi.mocked(financeRetirement.project).mock.calls.length
    fireEvent.change(screen.getByTestId('ret-age'), { target: { value: '60' } })
    await waitFor(() =>
      expect(vi.mocked(financeRetirement.project).mock.calls.length).toBeGreaterThan(calls),
    )
    const last = vi.mocked(financeRetirement.project).mock.calls.at(-1)![0]
    expect(last.retirement_age).toBe(60)
  })

  it('cold-start shows the setup state', async () => {
    vi.mocked(financeRetirement.getInputs).mockResolvedValue({
      has_inputs: false,
      prefill: { ...PREFILL, current_age: null, annual_contribution: null },
    })
    vi.mocked(financeRetirement.project).mockResolvedValue({
      needs_inputs: true, disclaimer: 'These projections are estimates, not advice.',
    })
    render(<RetirementPlanner />)
    await waitFor(() => expect(screen.getByTestId('ret-setup')).toBeTruthy())
  })
})
