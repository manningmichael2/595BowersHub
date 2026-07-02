import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ActionCenter, type DashboardAction } from '../ActionCenter'

const action = (over: Partial<DashboardAction>): DashboardAction => ({
  id: 'disk:/data', level: 'warning', title: 'Disk /data at 96%',
  detail: 'Free up space — the host is running low.', ...over,
})

describe('ActionCenter', () => {
  it('renders nothing when there are no actions', () => {
    const { container } = render(<ActionCenter actions={[]} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a card with title + detail', () => {
    render(<ActionCenter actions={[action({})]} />)
    expect(screen.getByText('Disk /data at 96%')).toBeTruthy()
    expect(screen.getByText(/free up space/i)).toBeTruthy()
  })

  it('dismisses a card and hides the strip when the last one is dismissed', () => {
    render(<ActionCenter actions={[action({})]} />)
    fireEvent.click(screen.getByRole('button', { name: /dismiss/i }))
    expect(screen.queryByText('Disk /data at 96%')).toBeNull()
  })

  it('keeps other cards when one is dismissed', () => {
    render(<ActionCenter actions={[action({}), action({ id: 'memory', title: 'Memory at 92%' })]} />)
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss Disk /data at 96%' }))
    expect(screen.queryByText('Disk /data at 96%')).toBeNull()
    expect(screen.getByText('Memory at 92%')).toBeTruthy()
  })
})
