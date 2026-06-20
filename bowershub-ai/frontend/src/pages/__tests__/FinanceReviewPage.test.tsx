/**
 * Component tests for FinanceReviewPage (Task 12 / R4.1, R1.6).
 *
 *   1. Queue renders rows from the API with prediction + confidence + rationale
 *      chips and a "transfer?" badge.
 *   2. Inline correct calls categorize; "apply to all from this merchant" calls
 *      applyToMerchant instead.
 *   3. Multi-select bulk-apply calls bulkCategorize with the selected ids.
 *   4. MerchantLogo falls back to a letter avatar on image error (no broken img).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'

vi.mock('../../services/financeReview', () => ({
  financeReview: {
    getQueue: vi.fn(),
    getCategories: vi.fn(),
    getRecurring: vi.fn(),
    categorize: vi.fn(),
    bulkCategorize: vi.fn(),
    applyToMerchant: vi.fn(),
  },
}))
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../../stores/toast', () => ({
  toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() },
}))

import FinanceReviewPage from '../FinanceReviewPage'
import MerchantLogo from '../../components/MerchantLogo'
import { financeReview, type ReviewQueueItem } from '../../services/financeReview'

const CATEGORIES = [
  { id: 10, name: 'Food_Groceries', parent_id: null },
  { id: 11, name: 'Food_Dining', parent_id: null },
]

const ITEMS: ReviewQueueItem[] = [
  {
    id: 't1', description: 'SQ *SUNRISE BAKERY', amount: -6.75, posted_date: '2026-06-01',
    account_id: 'a1', merchant_key: 'SUNRISE BAKERY', predicted_category_id: 11,
    predicted_category_name: 'Food_Dining', confidence: 0.62, tier: 'embedding_knn',
    transfer_suspected: false, rationale: { source: 'merchant_knn' },
  },
  {
    id: 't2', description: 'TRANSFER TO SAVINGS', amount: -500, posted_date: '2026-06-02',
    account_id: 'a1', merchant_key: 'TRANSFER TO SAVINGS', predicted_category_id: null,
    predicted_category_name: null, confidence: 0.5, tier: 'transfer',
    transfer_suspected: true, rationale: { method: 'descriptor_single_leg' },
  },
]

const mocked = financeReview as unknown as Record<string, ReturnType<typeof vi.fn>>

function primeQueue(items = ITEMS) {
  mocked.getQueue.mockResolvedValue({ items, count: items.length })
  mocked.getCategories.mockResolvedValue(CATEGORIES)
  mocked.getRecurring.mockResolvedValue([])
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe('FinanceReviewPage', () => {
  it('renders queue rows with prediction + transfer chips', async () => {
    primeQueue()
    render(<FinanceReviewPage />)
    await waitFor(() => expect(screen.getAllByTestId('queue-row')).toHaveLength(2))
    expect(screen.getByText(/Food_Dining · 62%/)).toBeTruthy()
    expect(screen.getByTestId('transfer-chip').textContent).toContain('transfer?')
  })

  it('inline correct calls categorize for a single transaction', async () => {
    primeQueue()
    mocked.categorize.mockResolvedValue(undefined)
    render(<FinanceReviewPage />)
    await waitFor(() => expect(screen.getAllByTestId('queue-row')).toHaveLength(2))

    const row = screen.getAllByTestId('queue-row')[0]
    fireEvent.change(within(row).getByLabelText(/Category for/), { target: { value: '10' } })
    fireEvent.click(within(row).getByText('Save'))

    await waitFor(() => expect(mocked.categorize).toHaveBeenCalledWith('t1', 10))
    expect(mocked.applyToMerchant).not.toHaveBeenCalled()
  })

  it('"apply to all from merchant" routes to applyToMerchant', async () => {
    primeQueue()
    mocked.applyToMerchant.mockResolvedValue({ merchant_key: 'SUNRISE BAKERY', updated: 3, rule_id: null })
    render(<FinanceReviewPage />)
    await waitFor(() => expect(screen.getAllByTestId('queue-row')).toHaveLength(2))

    const row = screen.getAllByTestId('queue-row')[0]
    fireEvent.change(within(row).getByLabelText(/Category for/), { target: { value: '11' } })
    fireEvent.click(within(row).getByLabelText(/all SUNRISE BAKERY/))
    fireEvent.click(within(row).getByText('Save'))

    await waitFor(() =>
      expect(mocked.applyToMerchant).toHaveBeenCalledWith('SUNRISE BAKERY', 11, { setPrior: true }))
    expect(mocked.categorize).not.toHaveBeenCalled()
  })

  it('bulk-apply calls bulkCategorize with the selected ids', async () => {
    primeQueue()
    mocked.bulkCategorize.mockResolvedValue(2)
    render(<FinanceReviewPage />)
    await waitFor(() => expect(screen.getAllByTestId('queue-row')).toHaveLength(2))

    fireEvent.click(screen.getByLabelText(/Select SQ \*SUNRISE BAKERY/))
    fireEvent.click(screen.getByLabelText(/Select TRANSFER TO SAVINGS/))
    fireEvent.change(screen.getByLabelText('Bulk category'), { target: { value: '10' } })
    fireEvent.click(screen.getByText('Apply to selected'))

    await waitFor(() =>
      expect(mocked.bulkCategorize).toHaveBeenCalledWith(['t1', 't2'], 10))
  })
})

describe('MerchantLogo (R1.6 graceful degradation)', () => {
  it('shows the favicon image, then falls back to an avatar on error', () => {
    render(<MerchantLogo merchantKey="COSTCO" />)
    const img = screen.getByTestId('merchant-logo-img')
    fireEvent.error(img)
    expect(screen.getByTestId('merchant-logo-fallback').textContent).toBe('CO')
  })

  it('renders the avatar immediately when there is no merchant key', () => {
    render(<MerchantLogo merchantKey={null} />)
    expect(screen.getByTestId('merchant-logo-fallback').textContent).toBe('?')
    expect(screen.queryByTestId('merchant-logo-img')).toBeNull()
  })
})
