/**
 * Component tests for BudgetsPage (finance-budgets-splits Task 8 / R3.4).
 *   1. Renders Budgeted/Spent/Remaining rows with budgetTone coloring.
 *   2. Editing a limit calls setBudget.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../../services/financeBudgets', () => ({
  financeBudgets: { getActual: vi.fn(), setBudget: vi.fn() },
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../../stores/toast', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

import BudgetsPage from '../BudgetsPage'
import { financeBudgets, type BudgetActual } from '../../services/financeBudgets'

const ROWS: BudgetActual[] = [
  { category_id: 1, category: 'Groceries', budgeted: 500, actual: 520, remaining: -20 }, // over
  { category_id: 2, category: 'Dining', budgeted: 200, actual: 80, remaining: 120 },      // ok
]

afterEach(cleanup)

describe('BudgetsPage', () => {
  it('renders rows with tone and over-budget coloring', async () => {
    vi.mocked(financeBudgets.getActual).mockResolvedValue(ROWS)
    render(<BudgetsPage />)
    await waitFor(() => expect(screen.getByText('Groceries')).toBeTruthy())
    expect(screen.getByText('Dining')).toBeTruthy()
    expect(screen.getByTestId('tone-over')).toBeTruthy()  // 520/500 → over
    expect(screen.getByTestId('tone-ok')).toBeTruthy()    // 80/200 → ok
  })

  it('editing a limit calls setBudget', async () => {
    vi.mocked(financeBudgets.getActual).mockResolvedValue(ROWS)
    vi.mocked(financeBudgets.setBudget).mockResolvedValue()
    render(<BudgetsPage />)
    await waitFor(() => expect(screen.getByText('Dining')).toBeTruthy())
    const input = screen.getByLabelText('Budget for Dining')
    fireEvent.change(input, { target: { value: '300' } })
    fireEvent.blur(input)
    await waitFor(() => expect(financeBudgets.setBudget).toHaveBeenCalledWith(2, expect.any(String), 300))
  })
})
