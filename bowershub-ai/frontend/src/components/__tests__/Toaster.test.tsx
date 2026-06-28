/**
 * Toaster re-skin (T6 / R2.4): verifies the tokenized container, the preserved
 * action button (PWA "Reload" flow) and dismiss, with no hardcoded palette.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import Toaster from '../Toaster'
import { useToastStore } from '../../stores/toast'

afterEach(() => {
  cleanup()
  useToastStore.setState({ toasts: [] })
})

describe('Toaster', () => {
  it('renders a tokenized error toast (no hardcoded palette)', () => {
    useToastStore.setState({ toasts: [{ id: 1, type: 'error', message: 'Boom' }] as any })
    render(<Toaster />)
    const alert = screen.getByRole('alert')
    expect(screen.getByText('Boom')).toBeTruthy()
    expect(alert.className).toContain('bg-danger')
    expect(alert.className).toContain('text-on-danger')
    expect(alert.className).not.toMatch(/bg-(red|green|neutral)-\d/)
  })

  it('fires the action then dismisses', () => {
    const onClick = vi.fn()
    useToastStore.setState({
      toasts: [{ id: 2, type: 'info', message: 'Update', action: { label: 'Reload', onClick } }] as any,
    })
    render(<Toaster />)
    fireEvent.click(screen.getByRole('button', { name: 'Reload' }))
    expect(onClick).toHaveBeenCalledOnce()
    expect(useToastStore.getState().toasts).toHaveLength(0)
  })

  it('dismiss button removes the toast', () => {
    useToastStore.setState({ toasts: [{ id: 3, type: 'success', message: 'Saved' }] as any })
    render(<Toaster />)
    fireEvent.click(screen.getByRole('button', { name: 'Dismiss notification' }))
    expect(useToastStore.getState().toasts).toHaveLength(0)
  })
})
