/**
 * Component test for `QuickCaptureOverlay`.
 *
 * Covers task 26.4 (happy-path slice):
 *   - User types text and clicks Save → `POST /api/quick-capture/extract`
 *     (R9.2). Component transitions to the confirm view rendering the
 *     extracted intents.
 *   - User clicks Confirm → `POST /api/quick-capture/commit` is called
 *     once per accepted intent (R9.4). Component shows a success
 *     summary and `onClose` is invoked with the summary string.
 *
 * Mocking strategy:
 *   - `services/api` is `vi.mock`'d so no real `fetch` is exercised.
 *     The mock's `post` function is queued per-test to drive the
 *     extract → commit chain.
 *   - The auth and workspace stores are seeded directly via their
 *     `setState` APIs (same pattern as `IconUploader.test.tsx`) so the
 *     component reads a known active workspace and bearer token.
 *   - `vi.useFakeTimers()` advances the post-success auto-close timer
 *     deterministically (the component schedules `onClose` 1.2s after
 *     a successful commit).
 *
 * _Requirements: R9.2 (extract), R9.4 (per-intent commit + success toast)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import QuickCaptureOverlay from '../QuickCaptureOverlay'
import { useAuthStore } from '../../stores/auth'
import { useWorkspaceStore, type Workspace } from '../../stores/workspace'

// ---- API mock -------------------------------------------------------------

vi.mock('../../services/api', () => {
  return {
    api: {
      get: vi.fn(),
      post: vi.fn(),
      patch: vi.fn(),
      delete: vi.fn(),
    },
  }
})

// Late-bound import so the mock is in place when the module resolves.
import { api } from '../../services/api'

// ---- Fixtures -------------------------------------------------------------

const ACTIVE_WORKSPACE: Workspace = {
  id: 3,
  name: 'Woodshop',
  description: null,
  icon: null,
  color: null,
  system_prompt: '',
  default_model: 'claude-sonnet-4-5',
  auto_capture: false,
  user_count: 1,
  skill_count: 0,
}

const EXTRACT_RESPONSE = {
  ok: true,
  intents: [
    {
      domain: 'knowledge_fact',
      summary: 'Bought a new Festool TS 60 saw blade',
      payload: { fact: 'TS 60 blade purchased', topic: 'woodshop/saws' },
    },
    {
      domain: 'shopping_list',
      summary: 'Add: 1/2-inch shank straight bit',
      payload: { item: '1/2-inch shank straight bit' },
    },
  ],
  asset: null,
  raw_text: 'bought a new TS 60 blade and need a 1/2-inch shank straight bit',
  extract_token: 'tok_test_abc123',
}

// ---- Lifecycle ------------------------------------------------------------

beforeEach(() => {
  // Seed auth + workspace state — the component reads both directly.
  useAuthStore.setState({
    user: {
      id: 1,
      email: 'admin@example.com',
      display_name: 'Admin',
      role: 'admin',
      is_active: true,
    },
    accessToken: 'test-bearer-token',
    refreshToken: null,
    isLoading: false,
    error: null,
    isRefreshing: false,
  } as any)

  useWorkspaceStore.setState({
    workspaces: [ACTIVE_WORKSPACE],
    activeWorkspace: ACTIVE_WORKSPACE,
    isLoading: false,
  } as any)

  ;(api.get as any).mockReset?.()
  ;(api.post as any).mockReset?.()
  ;(api.patch as any).mockReset?.()
  ;(api.delete as any).mockReset?.()
})

afterEach(() => {
  cleanup()
  vi.useRealTimers()
  vi.restoreAllMocks()
})

// ---- Tests ----------------------------------------------------------------

describe('QuickCaptureOverlay — extract → confirm → commit happy path', () => {
  it('walks the user through extract, renders intents, then commits each accepted intent', async () => {
    // Per-call routing on the mocked api client. Extract returns the
    // canned response; commit always succeeds (we expect two commit
    // calls, one per accepted intent).
    ;(api.post as any).mockImplementation(
      async (path: string, _body: unknown) => {
        if (path === '/api/quick-capture/extract') {
          return { data: EXTRACT_RESPONSE, status: 200 }
        }
        if (path === '/api/quick-capture/commit') {
          return { data: { ok: true }, status: 200 }
        }
        throw new Error(`Unexpected path: ${path}`)
      },
    )

    const onClose = vi.fn()

    // Use fake timers so the post-success auto-close (1200ms) is
    // deterministic.
    vi.useFakeTimers({ shouldAdvanceTime: true })

    render(<QuickCaptureOverlay onClose={onClose} />)

    // ---- Compose view ----
    // The textarea is focused on mount; the dialog title confirms we
    // landed on the right component.
    expect(screen.getByText('⚡ Quick Capture')).toBeTruthy()

    const textarea = screen.getByPlaceholderText(
      /What's on your mind/i,
    ) as HTMLTextAreaElement
    fireEvent.change(textarea, {
      target: {
        value: 'bought a new TS 60 blade and need a 1/2-inch shank straight bit',
      },
    })

    // The Save button enables once we have text + an active workspace.
    const saveBtn = screen.getByRole('button', { name: /^save$/i })
    expect((saveBtn as HTMLButtonElement).disabled).toBe(false)

    // ---- Click Save → extract ----
    await act(async () => {
      fireEvent.click(saveBtn)
    })

    // Extract was called with text + the active workspace id (R9.2, R9.8).
    await waitFor(() => {
      expect((api.post as any)).toHaveBeenCalledWith(
        '/api/quick-capture/extract',
        expect.objectContaining({
          text: 'bought a new TS 60 blade and need a 1/2-inch shank straight bit',
          workspace_id: ACTIVE_WORKSPACE.id,
        }),
      )
    })

    // ---- Confirm view ----
    // Both extracted intent summaries are visible.
    expect(
      await screen.findByText('Bought a new Festool TS 60 saw blade'),
    ).toBeTruthy()
    expect(screen.getByText('Add: 1/2-inch shank straight bit')).toBeTruthy()

    // Both checkboxes default to checked (the user accepts everything
    // by default and unticks what they don't want).
    const checkboxes = screen.getAllByRole(
      'checkbox',
    ) as HTMLInputElement[]
    expect(checkboxes).toHaveLength(2)
    expect(checkboxes.every(cb => cb.checked)).toBe(true)

    // ---- Click Confirm → commit ----
    const confirmBtn = screen.getByRole('button', { name: /^confirm$/i })
    await act(async () => {
      fireEvent.click(confirmBtn)
    })

    // Commit fires once per accepted intent (R9.4).
    await waitFor(() => {
      const commitCalls = (api.post as any).mock.calls.filter(
        (c: any[]) => c[0] === '/api/quick-capture/commit',
      )
      expect(commitCalls).toHaveLength(2)
    })

    // Each commit body carries the extract token (R9.2 token plumbing)
    // and the per-intent domain + payload.
    const commitCalls = (api.post as any).mock.calls.filter(
      (c: any[]) => c[0] === '/api/quick-capture/commit',
    )
    for (const [, body] of commitCalls) {
      expect(body).toEqual(
        expect.objectContaining({
          extract_token: EXTRACT_RESPONSE.extract_token,
          workspace_id: ACTIVE_WORKSPACE.id,
        }),
      )
      expect(['knowledge_fact', 'shopping_list']).toContain(body.domain)
    }

    // Success view appears with a summary line. The exact prefix is
    // "Saved …" — match loosely so domain-name pluralization stays an
    // implementation detail of the component.
    expect(await screen.findByText(/^Saved /)).toBeTruthy()

    // ---- Auto-close ----
    // The component schedules onClose for ~1.2s after success. Advance
    // the fake timers and assert the parent was notified with the
    // summary string.
    await act(async () => {
      vi.advanceTimersByTime(1500)
    })
    await waitFor(() => {
      expect(onClose).toHaveBeenCalled()
    })
    const closeArg = (onClose as any).mock.calls.at(-1)?.[0]
    expect(typeof closeArg).toBe('string')
    expect(closeArg).toMatch(/^Saved /)
  })
})
