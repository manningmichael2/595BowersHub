/**
 * Load-path tests for the workspace store — the bug that kicked off the whole
 * "empty chat drawer" investigation lived here:
 *  - a stale `activeWorkspaceId` (a workspace that no longer exists) must fall
 *    back to the first workspace, never leave `activeWorkspace` null; and
 *  - a genuine fetch failure must be recorded as an error, not rendered as a
 *    silent empty account.
 */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { useWorkspaceStore } from '../workspace'

function ws(id: number, name: string) {
  return {
    id,
    name,
    description: null,
    icon: null,
    color: null,
    system_prompt: '',
    default_model: 'auto',
    auto_capture: false,
    user_count: 1,
    skill_count: 0,
  }
}

function okJson(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data,
  } as unknown as Response
}

describe('workspace store load path', () => {
  beforeEach(() => {
    localStorage.clear()
    useWorkspaceStore.setState({
      workspaces: [],
      activeWorkspace: null,
      isLoading: false,
      error: null,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('falls back to the first workspace when the saved id no longer exists (deadlock fix)', async () => {
    localStorage.setItem('activeWorkspaceId', '999') // stale — not in the returned list
    vi.stubGlobal('fetch', vi.fn(async () => okJson([ws(1, 'A'), ws(2, 'B')])))

    await useWorkspaceStore.getState().fetchWorkspaces()

    const s = useWorkspaceStore.getState()
    expect(s.workspaces).toHaveLength(2)
    expect(s.activeWorkspace?.id).toBe(1) // fell back, not stuck null
    expect(localStorage.getItem('activeWorkspaceId')).toBe('1') // healed the stale pointer
    expect(s.error).toBeNull()
  })

  it('restores the saved workspace when it still exists', async () => {
    localStorage.setItem('activeWorkspaceId', '2')
    vi.stubGlobal('fetch', vi.fn(async () => okJson([ws(1, 'A'), ws(2, 'B')])))

    await useWorkspaceStore.getState().fetchWorkspaces()

    expect(useWorkspaceStore.getState().activeWorkspace?.id).toBe(2)
    expect(localStorage.getItem('activeWorkspaceId')).toBe('2') // untouched
  })

  it('records an error (not a silent empty) when the fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down') }))

    await useWorkspaceStore.getState().fetchWorkspaces()

    const s = useWorkspaceStore.getState()
    expect(s.workspaces).toHaveLength(0)
    expect(s.activeWorkspace).toBeNull()
    expect(s.error).toBeTruthy() // the UI shows "couldn't load — Retry" off this
  })
})
