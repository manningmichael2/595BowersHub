/**
 * Component tests for FinanceQaPage (ai-finance-insights Task 3 / R1.2, R1.4, R1.6).
 *   1. An in-scope answer renders and reveals the SQL + figures (verifiability).
 *   2. Empty (R1.6) and out-of-scope (R1.4) answers render distinctly (data-scope).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../../services/financeQa', () => ({
  financeQa: { ask: vi.fn() },
}))

import FinanceQaPage from '../FinanceQaPage'
import { financeQa, type QaResponse } from '../../services/financeQa'

afterEach(cleanup)

async function ask(question = 'how much on coffee?') {
  render(<FinanceQaPage />)
  fireEvent.change(screen.getByTestId('qa-input'), { target: { value: question } })
  fireEvent.click(screen.getByText('Ask'))
}

describe('FinanceQaPage', () => {
  it('renders an in-scope answer and reveals query + figures', async () => {
    const resp: QaResponse = {
      answer: 'You spent $19.75 at coffee shops.',
      sql: 'SELECT sum(amount) AS total FROM finance.transactions',
      figures: [{ total: -19.75 }],
      scope: 'in_scope',
    }
    vi.mocked(financeQa.ask).mockResolvedValue(resp)
    await ask()

    await waitFor(() => expect(screen.getByTestId('qa-result')).toBeTruthy())
    expect(screen.getByTestId('qa-result').getAttribute('data-scope')).toBe('in_scope')
    expect(screen.getByText(/coffee shops/)).toBeTruthy()

    // Figures hidden until revealed (verifiability is opt-in).
    expect(screen.queryByText(/SELECT sum/)).toBeNull()
    fireEvent.click(screen.getByTestId('qa-reveal'))
    await waitFor(() => expect(screen.getByText(/SELECT sum/)).toBeTruthy())
    expect(screen.getByText(/-19\.75/)).toBeTruthy()
  })

  it('renders empty and out-of-scope answers distinctly', async () => {
    vi.mocked(financeQa.ask).mockResolvedValue({
      answer: 'No matching financial activity found for that question.',
      sql: 'SELECT * FROM finance.transactions',
      figures: [],
      scope: 'empty',
    })
    await ask('any rent?')
    await waitFor(() =>
      expect(screen.getByTestId('qa-result').getAttribute('data-scope')).toBe('empty'),
    )
    cleanup()

    vi.mocked(financeQa.ask).mockResolvedValue({
      answer: "That's outside what I can see — I can only read your finance data.",
      sql: null,
      figures: [],
      scope: 'out_of_scope',
    })
    await ask('list users')
    await waitFor(() =>
      expect(screen.getByTestId('qa-result').getAttribute('data-scope')).toBe('out_of_scope'),
    )
  })
})
