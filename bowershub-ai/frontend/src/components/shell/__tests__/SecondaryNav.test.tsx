/**
 * SecondaryNav (T12 / R3.3): the shared in-section nav primitive renders items
 * as links with active state and an accessible landmark.
 */
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { SecondaryNav } from '../SecondaryNav'

afterEach(cleanup)

describe('SecondaryNav', () => {
  it('renders items as links under a labelled nav landmark, marking the active one', () => {
    render(
      <MemoryRouter initialEntries={['/finance/insights']}>
        <SecondaryNav
          label="Finance"
          items={[
            { to: '/finance/transactions', label: 'Transactions' },
            { to: '/finance/insights', label: 'Insights' },
          ]}
        />
      </MemoryRouter>,
    )
    expect(screen.getByRole('navigation', { name: 'Finance' })).toBeTruthy()
    const active = screen.getByRole('link', { name: 'Insights' })
    expect(active.getAttribute('aria-current')).toBe('page')
    expect(screen.getByRole('link', { name: 'Transactions' }).getAttribute('aria-current')).toBeNull()
  })
})
