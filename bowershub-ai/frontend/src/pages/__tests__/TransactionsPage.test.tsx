/**
 * Component tests for TransactionsPage (Finance → Transactions explorer).
 *   1. Renders rows + totals + by-category subtotals.
 *   2. Clicking a column header re-queries with that sort.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../../services/financeTransactions', () => ({ financeTransactions: { search: vi.fn() } }))
vi.mock('../../services/financeReview', () => ({ financeReview: { getCategories: vi.fn().mockResolvedValue([]) } }))
vi.mock('../../stores/toast', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

import TransactionsPage from '../TransactionsPage'
import { financeTransactions, type TxnSearchResult } from '../../services/financeTransactions'

const RESULT: TxnSearchResult = {
  items: [
    { id: 't1', posted_date: '2026-06-01', description: 'COSTCO', merchant_key: 'COSTCO', amount: -40, account_id: 'a', account_name: 'Chk', category_id: 1, category_name: 'Groceries', is_transfer: false, is_investment: false, is_split: false, cleared: false },
  ],
  count: 1,
  subtotals: [{ category: 'Groceries', total: -40, count: 1 }],
  totals: { income: 0, spending: 40 },
}

afterEach(cleanup)

describe('TransactionsPage', () => {
  it('renders rows, totals, and subtotals', async () => {
    vi.mocked(financeTransactions.search).mockResolvedValue(RESULT)
    render(<TransactionsPage />)
    await waitFor(() => expect(screen.getByTestId('txn-row')).toBeTruthy())
    expect(screen.getByText('COSTCO')).toBeTruthy()
    expect(screen.getAllByText('Groceries').length).toBeGreaterThanOrEqual(2) // row cell + subtotal
    expect(screen.getByText('$40.00')).toBeTruthy()        // spending total
  })

  it('clicking the Amount header re-queries sorted by amount', async () => {
    vi.mocked(financeTransactions.search).mockResolvedValue(RESULT)
    render(<TransactionsPage />)
    await waitFor(() => expect(screen.getByTestId('txn-row')).toBeTruthy())
    vi.mocked(financeTransactions.search).mockClear()
    fireEvent.click(screen.getByText(/^Amount/))
    await waitFor(() => expect(financeTransactions.search).toHaveBeenCalledWith(
      expect.objectContaining({ sort: 'amount' })))
  })
})
