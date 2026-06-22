/**
 * Regression test for the token-refresh single-flight (stores/auth.ts).
 *
 * Background: the backend rotates the refresh token on every /api/auth/refresh
 * and treats reuse of an already-rotated token as theft → it revokes ALL the
 * user's sessions. On app load many requests fire at once; if the access token
 * is stale they 401 together. Without de-duping, each 401 would POST /refresh
 * with the same rotating token — the first consumes it, the rest replay a
 * revoked token and nuke the session, leaving the UI with empty data.
 *
 * The fix holds one shared in-flight refresh promise so concurrent callers
 * await the SAME round-trip. These tests lock that behavior in.
 */
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '../auth'

function refreshOk(n: number): Response {
  return {
    ok: true,
    json: async () => ({ access_token: `access-${n}`, refresh_token: `refresh-${n}` }),
  } as Response
}

describe('auth refreshAuth single-flight', () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({
      user: null,
      accessToken: null,
      refreshToken: 'rt-0',
      isRefreshing: false,
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('coalesces concurrent refreshes into a single /api/auth/refresh call', async () => {
    let refreshCalls = 0
    const fetchMock = vi.fn(async (url: unknown) => {
      if (typeof url === 'string' && url.includes('/api/auth/refresh')) {
        refreshCalls++
        // Latency so all five callers genuinely overlap before any resolves.
        await new Promise((r) => setTimeout(r, 20))
        return refreshOk(refreshCalls)
      }
      return { ok: false, json: async () => ({ detail: 'unexpected' }) } as Response
    })
    vi.stubGlobal('fetch', fetchMock)

    const results = await Promise.all(
      Array.from({ length: 5 }, () => useAuthStore.getState().refreshAuth()),
    )

    // The whole point: one network round-trip, so the rotating token is
    // consumed exactly once and the backend never sees a replayed token.
    expect(refreshCalls).toBe(1)
    expect(results).toEqual([true, true, true, true, true])
    // All callers see the single freshly-rotated token.
    expect(useAuthStore.getState().accessToken).toBe('access-1')
    expect(useAuthStore.getState().refreshToken).toBe('refresh-1')
  })

  it('does not dedupe sequential (non-overlapping) refreshes', async () => {
    const fetchMock = vi.fn(async () => {
      await new Promise((r) => setTimeout(r, 5))
      return refreshOk(1)
    })
    vi.stubGlobal('fetch', fetchMock)

    await useAuthStore.getState().refreshAuth()
    await useAuthStore.getState().refreshAuth()

    // The shared promise is released once it settles, so a later refresh
    // performs its own round-trip (it isn't permanently pinned to the first).
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
