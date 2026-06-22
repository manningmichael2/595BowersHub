/**
 * Component tests for InsightsPage (ai-finance-insights Task 10 / R2.5, R2.6).
 *   1. Renders active insights ranked, with reason + impact.
 *   2. Dismiss calls the API and reloads.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../../services/financeInsights', () => ({
  financeInsights: { list: vi.fn(), dismiss: vi.fn(), reopen: vi.fn(), action: vi.fn() },
}))
vi.mock('../../services/financeRules', () => ({
  financeRules: { parse: vi.fn(), create: vi.fn() },
}))
vi.mock('../../services/financeReview', () => ({
  financeReview: { getCategories: vi.fn() },
}))
vi.mock('../../stores/toast', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

import InsightsPage from '../InsightsPage'
import { financeInsights, type Insight } from '../../services/financeInsights'
import { financeRules } from '../../services/financeRules'

const ROWS: Insight[] = [
  {
    id: 1, insight_type: 'price_creep', merchant_key: 'netflix', period: '2026-06',
    status: 'active', dollar_impact: 5.0, figures: { latest: 15, prior_avg: 10 },
    reason: 'Netflix rose to $15.00 from $10.00', created_at: null,
  },
]

afterEach(cleanup)

describe('InsightsPage', () => {
  it('renders active insights with reason and impact', async () => {
    vi.mocked(financeInsights.list).mockResolvedValue(ROWS)
    render(<InsightsPage />)
    await waitFor(() => expect(screen.getByTestId('insight-row')).toBeTruthy())
    expect(screen.getByText(/Netflix rose to \$15\.00/)).toBeTruthy()
    expect(screen.getByText('$5.00')).toBeTruthy()
  })

  it('dismiss calls the API and reloads', async () => {
    vi.mocked(financeInsights.list).mockResolvedValue(ROWS)
    vi.mocked(financeInsights.dismiss).mockResolvedValue()
    render(<InsightsPage />)
    await waitFor(() => expect(screen.getByText('Dismiss')).toBeTruthy())
    fireEvent.click(screen.getByText('Dismiss'))
    await waitFor(() => expect(financeInsights.dismiss).toHaveBeenCalledWith(1))
  })

  it('NL rule composer previews then commits', async () => {
    vi.mocked(financeInsights.list).mockResolvedValue([])
    vi.mocked(financeRules.parse).mockResolvedValue({
      candidate: {
        priority: 100, category_id: 3, merchant_key: 'whole foods', description_regex: null,
        amount_min: -200, amount_max: null, account_id: null, is_active: true,
      },
      category_name: 'Groceries', merchant_key: 'whole foods', preview_count: 7,
    })
    vi.mocked(financeRules.create).mockResolvedValue()
    render(<InsightsPage />)

    fireEvent.change(screen.getByTestId('nl-rule-input'), {
      target: { value: 'Whole Foods as Groceries unless over $200' },
    })
    fireEvent.click(screen.getByText('Preview'))
    await waitFor(() => expect(screen.getByTestId('nl-rule-preview')).toBeTruthy())
    expect(screen.getByText(/affects/)).toBeTruthy()
    expect(screen.getByText('7')).toBeTruthy()

    fireEvent.click(screen.getByText('Create rule'))
    await waitFor(() => expect(financeRules.create).toHaveBeenCalled())
  })
})
