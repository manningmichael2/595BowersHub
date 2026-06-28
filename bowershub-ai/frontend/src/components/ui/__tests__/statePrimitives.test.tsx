/**
 * State primitives (T7 / R2.6): Spinner, Skeleton, EmptyState, ErrorState,
 * FieldError.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Spinner, Skeleton, EmptyState, ErrorState, FieldError, Button } from '..'

afterEach(cleanup)

describe('Spinner', () => {
  it('exposes role=status and a label', () => {
    render(<Spinner label="Loading data" />)
    expect(screen.getByRole('status').getAttribute('aria-label')).toBe('Loading data')
  })
})

describe('Skeleton', () => {
  it('renders a pulsing placeholder', () => {
    const { container } = render(<Skeleton className="h-4 w-20" />)
    expect(container.firstElementChild?.className).toContain('animate-pulse')
  })
})

describe('EmptyState', () => {
  it('renders title, description and action', () => {
    render(
      <EmptyState
        title="No transactions"
        description="Connect an account to begin."
        action={<Button>Connect</Button>}
      />,
    )
    expect(screen.getByText('No transactions')).toBeTruthy()
    expect(screen.getByText('Connect an account to begin.')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Connect' })).toBeTruthy()
  })
})

describe('ErrorState', () => {
  it('shows the retry affordance and fires onRetry', () => {
    const onRetry = vi.fn()
    render(<ErrorState message="Network down" onRetry={onRetry} />)
    expect(screen.getByRole('alert')).toBeTruthy()
    expect(screen.getByText('Network down')).toBeTruthy()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('omits the retry button when no handler is given', () => {
    render(<ErrorState message="oops" />)
    expect(screen.queryByRole('button')).toBeNull()
  })
})

describe('FieldError', () => {
  it('renders nothing when empty, and an alert when populated', () => {
    const { rerender, container } = render(<FieldError>{''}</FieldError>)
    expect(container.firstChild).toBeNull()
    rerender(<FieldError>Required</FieldError>)
    expect(screen.getByRole('alert').textContent).toBe('Required')
  })
})
