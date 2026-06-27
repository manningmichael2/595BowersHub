/**
 * Finance widgets (T8 / R2.5). React Aria's interaction internals are tested
 * upstream; here we verify our wrappers render through the boundary, format,
 * and project the right structure (labels, formatted currency, grid cells).
 */
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { CurrencyInput, Combobox, DatePicker, DataGrid } from '..'

afterEach(cleanup)

describe('CurrencyInput', () => {
  it('formats a numeric value as currency', () => {
    const { container } = render(<CurrencyInput label="Amount" value={1234.5} aria-label="Amount" />)
    expect(screen.getByText('Amount')).toBeTruthy()
    const input = container.querySelector('input')!
    expect(input.value).toContain('1,234.50')
    expect(input.value).toContain('$')
  })
})

describe('Combobox', () => {
  it('renders a labelled combobox input', () => {
    render(
      <Combobox
        label="Category"
        placeholder="Pick one"
        options={[
          { id: 'a', label: 'Groceries' },
          { id: 'b', label: 'Rent' },
        ]}
      />,
    )
    expect(screen.getByText('Category')).toBeTruthy()
    expect(screen.getByRole('combobox')).toBeTruthy()
  })
})

describe('DatePicker', () => {
  it('renders a labelled date field with a calendar trigger', () => {
    const { container } = render(<DatePicker label="Date" />)
    expect(screen.getByText('Date')).toBeTruthy()
    // group + segments + a calendar trigger button render
    expect(screen.getByRole('group')).toBeTruthy()
    expect(container.querySelector('button')).toBeTruthy()
  })
})

describe('DataGrid', () => {
  it('renders columns and row cells from config', () => {
    type Row = { id: number; merchant: string; amount: string }
    render(
      <DataGrid<Row>
        aria-label="Transactions"
        getRowId={(r) => r.id}
        columns={[
          { id: 'merchant', header: 'Merchant', isRowHeader: true, render: (r) => r.merchant },
          { id: 'amount', header: 'Amount', render: (r) => r.amount },
        ]}
        rows={[
          { id: 1, merchant: 'Costco', amount: '$42.00' },
          { id: 2, merchant: 'Shell', amount: '$30.00' },
        ]}
      />,
    )
    expect(screen.getByRole('grid')).toBeTruthy()
    expect(screen.getByText('Merchant')).toBeTruthy()
    expect(screen.getByText('Costco')).toBeTruthy()
    expect(screen.getByText('$30.00')).toBeTruthy()
  })
})
