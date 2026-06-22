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
vi.mock('../../stores/toast', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

import InsightsPage from '../InsightsPage'
import { financeInsights, type Insight } from '../../services/financeInsights'

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
})
