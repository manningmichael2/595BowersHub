/**
 * Component tests for the settings sections wired up in the full-pass:
 * NotificationsPanel, BriefingPanel, and ContextCapturePanel.
 *
 * `services/api` is mocked so nothing leaves the runner. The settings/workspace
 * stores are seeded and their mutating methods swapped for spies, so we assert
 * the panels call them correctly without exercising the optimistic-update path.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('../../services/api', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}))
import { api } from '../../services/api'

import NotificationsPanel from '../NotificationsPanel'
import BriefingPanel from '../BriefingPanel'
import ContextCapturePanel from '../ContextCapturePanel'
import { useSettingsStore } from '../../stores/settings'
import { useWorkspaceStore } from '../../stores/workspace'

beforeEach(() => {
  ;(api.get as any).mockReset()
  ;(api.put as any).mockReset()
  ;(api.put as any).mockResolvedValue({ data: {} })

  useSettingsStore.setState({
    settings: {},
    patch: vi.fn().mockResolvedValue(undefined) as any,
  })
})

afterEach(() => cleanup())

// ---- NotificationsPanel ---------------------------------------------------

describe('NotificationsPanel', () => {
  it('greys out a channel the server cannot deliver', async () => {
    ;(api.get as any).mockResolvedValue({
      data: {
        prefs: { web_push: true, pushover: false, quiet_start: null, quiet_end: null },
        available: { web_push: true, pushover: false },
      },
    })
    render(<NotificationsPanel />)

    // Pushover switch is disabled (server has no Pushover config).
    const pushover = await screen.findByRole('switch', { name: 'Pushover' })
    expect((pushover as HTMLButtonElement).disabled).toBe(true)
    // Web push is available → enabled.
    expect((screen.getByRole('switch', { name: 'Web push' }) as HTMLButtonElement).disabled).toBe(
      false,
    )
  })

  it('PUTs the new prefs when a quiet-hours time is set', async () => {
    ;(api.get as any).mockResolvedValue({
      data: {
        prefs: { web_push: true, pushover: false, quiet_start: null, quiet_end: null },
        available: { web_push: true, pushover: true },
      },
    })
    render(<NotificationsPanel />)
    await screen.findByRole('switch', { name: 'Web push' })

    const from = screen.getByLabelText(/From/i)
    fireEvent.change(from, { target: { value: '22:00' } })

    await waitFor(() =>
      expect(api.put).toHaveBeenCalledWith(
        '/api/me/notifications',
        expect.objectContaining({ quiet_start: '22:00' }),
      ),
    )
  })
})

// ---- BriefingPanel --------------------------------------------------------

describe('BriefingPanel', () => {
  it('patches morning_card_disabled when the show-toggle is turned off', async () => {
    useWorkspaceStore.setState({ workspaces: [], fetchWorkspaces: vi.fn() as any })
    const patch = useSettingsStore.getState().patch as any
    render(<BriefingPanel />)

    fireEvent.click(screen.getByRole('switch', { name: 'Show the morning card' }))
    expect(patch).toHaveBeenCalledWith({ morning_card_disabled: true })
  })
})

// ---- ContextCapturePanel --------------------------------------------------

describe('ContextCapturePanel', () => {
  it('patches the opt-out when capture is turned off', () => {
    const patch = useSettingsStore.getState().patch as any
    render(<ContextCapturePanel />)

    // Default settings = enabled (checked); clicking turns it off.
    fireEvent.click(screen.getByRole('switch', { name: 'Enable context capture' }))
    expect(patch).toHaveBeenCalledWith({ context_capture_disabled: true })
  })
})
