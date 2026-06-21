/**
 * Component tests for NetWorthPage (finance-accounting Task 9 / R3.7, R4.1).
 *   1. Renders net worth + asset/liability breakdown rows.
 *   2. A needs-type account shows a set-type select that calls setAccountType.
 *   3. A stale account is flagged.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../../services/financeAccounting', async () => {
  const actual = await vi.importActual<typeof import('../../services/financeAccounting')>(
    '../../services/financeAccounting')
  return {
    ...actual,
    financeAccounting: {
      getNetWorth: vi.fn(),
      getHistory: vi.fn(),
      setAccountType: vi.fn(),
      reconcile: vi.fn(),
    },
  }
})
vi.mock('react-router-dom', () => ({ useNavigate: () => vi.fn() }))
vi.mock('../../stores/toast', () => ({ toast: { error: vi.fn(), success: vi.fn(), info: vi.fn() } }))

import NetWorthPage from '../NetWorthPage'
import { financeAccounting, type NetWorth } from '../../services/financeAccounting'

const NW: NetWorth = {
  net_worth: 1300, assets: 1500, liabilities: -200,
  accounts: [
    { id: 'a1', name: 'Checking', org: 'Bank', account_type: 'checking', balance: 1000, as_of: '2026-06-20', classification: 'asset', included: true, stale: false },
    { id: 'a2', name: 'Old Savings', org: 'Bank', account_type: 'savings', balance: 500, as_of: '2026-05-01', classification: 'asset', included: true, stale: true },
    { id: 'l1', name: 'Visa', org: 'Bank', account_type: 'credit_card', balance: -200, as_of: '2026-06-20', classification: 'liability', included: true, stale: false },
    { id: 'n1', name: 'Mystery', org: 'New', account_type: null, balance: 999, as_of: '2026-06-20', classification: 'needs_type', included: false, stale: false },
  ],
}

afterEach(cleanup)

describe('NetWorthPage', () => {
  it('renders net worth + accounts and flags stale + needs-type', async () => {
    vi.mocked(financeAccounting.getNetWorth).mockResolvedValue(NW)
    vi.mocked(financeAccounting.getHistory).mockResolvedValue([])
    render(<NetWorthPage />)
    await waitFor(() => expect(screen.getByText('$1,300.00')).toBeTruthy())
    expect(screen.getByText('Checking')).toBeTruthy()
    expect(screen.getByText('Visa')).toBeTruthy()
    expect(screen.getByText('Mystery')).toBeTruthy()
    expect(screen.getByTestId('stale')).toBeTruthy()
  })

  it('set-type on a needs-type account calls setAccountType', async () => {
    vi.mocked(financeAccounting.getNetWorth).mockResolvedValue(NW)
    vi.mocked(financeAccounting.getHistory).mockResolvedValue([])
    vi.mocked(financeAccounting.setAccountType).mockResolvedValue()
    render(<NetWorthPage />)
    await waitFor(() => expect(screen.getByText('Mystery')).toBeTruthy())
    fireEvent.change(screen.getByLabelText('Type for Mystery'), { target: { value: 'brokerage' } })
    await waitFor(() => expect(financeAccounting.setAccountType).toHaveBeenCalledWith('n1', 'brokerage'))
  })
})
