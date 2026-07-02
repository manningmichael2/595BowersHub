import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { TaskReelWidget, type AgentEvent } from '../TaskReelWidget'

const post = vi.fn().mockResolvedValue({ data: {}, status: 200 })
vi.mock('../../../services/api', () => ({ api: { post: (...a: unknown[]) => post(...a), patch: vi.fn(), put: vi.fn(), delete: vi.fn() } }))
const toastSuccess = vi.fn()
vi.mock('../../../stores/toast', () => ({ toast: { success: (m: string) => toastSuccess(m), error: vi.fn(), info: vi.fn() } }))

const ev = (over: Partial<AgentEvent>): AgentEvent => ({
  id: 1, created_at: new Date().toISOString(), source: 'categorizer',
  message: 'Categorized 12 transactions', level: 'success', action_payload: null, ...over,
})

describe('TaskReelWidget', () => {
  beforeEach(() => { post.mockClear(); toastSuccess.mockClear() })

  it('renders the empty state when there are no events', () => {
    render(<TaskReelWidget events={[]} />)
    expect(screen.getByText(/no recent activity/i)).toBeTruthy()
  })

  it('renders an event row (source + message)', () => {
    render(<TaskReelWidget events={[ev({})]} />)
    expect(screen.getByText('Categorized 12 transactions')).toBeTruthy()
    expect(screen.getByText(/categorizer/i)).toBeTruthy()
  })

  it('shows no action button when action_payload is absent', () => {
    render(<TaskReelWidget events={[ev({})]} />)
    expect(screen.queryByRole('button')).toBeNull()
  })

  it('fires the inline mutation and toasts success', async () => {
    const withAction = ev({
      id: 2, message: 'Processed $14.99 as Unknown', level: 'warning',
      action_payload: { label: 'Recategorize', type: 'mutation', endpoint: '/api/finance/x', method: 'POST', body: { id: 5 } },
    })
    render(<TaskReelWidget events={[withAction]} />)
    const btn = screen.getByRole('button', { name: 'Recategorize' })
    fireEvent.click(btn)
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/finance/x', { id: 5 }))
    await waitFor(() => expect(toastSuccess).toHaveBeenCalled())
    expect(screen.getByRole('button', { name: /done/i })).toBeTruthy()
  })
})
