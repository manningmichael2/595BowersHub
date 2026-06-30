/**
 * ApiClient request shaping (services/api.ts).
 *
 * Locks in the Track-2 hardening: the client is the single choke point for
 * auth-token injection, and it now handles FormData uploads (previously every
 * upload used a raw fetch that manually grabbed the token and skipped the 401
 * refresh). Two invariants matter:
 *   - JSON bodies get Content-Type: application/json and a stringified body;
 *   - FormData bodies are passed through untouched with NO Content-Type, so the
 *     browser sets the multipart boundary itself.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '../api'
import { useAuthStore } from '../../stores/auth'

function okJson(data: unknown): Response {
  return {
    ok: true,
    status: 200,
    headers: { get: () => 'application/json' },
    json: async () => data,
  } as unknown as Response
}

describe('ApiClient request shaping', () => {
  beforeEach(() => {
    useAuthStore.setState({ accessToken: 'tok-123' } as never)
  })
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('sends JSON bodies with an application/json content-type and the token', async () => {
    const fetchMock = vi.fn(async () => okJson({ ok: true }))
    vi.stubGlobal('fetch', fetchMock)

    await api.post('/api/thing', { a: 1 })

    const [, opts] = fetchMock.mock.calls[0]
    expect((opts.headers as Record<string, string>)['Content-Type']).toBe('application/json')
    expect((opts.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-123')
    expect(opts.body).toBe(JSON.stringify({ a: 1 }))
  })

  it('passes FormData through untouched and sets NO content-type (browser adds the boundary)', async () => {
    const fetchMock = vi.fn(async () => okJson({ files: [] }))
    vi.stubGlobal('fetch', fetchMock)

    const form = new FormData()
    form.append('file', new Blob(['x']), 'x.png')
    await api.post('/api/files/upload', form)

    const [, opts] = fetchMock.mock.calls[0]
    expect(opts.body).toBe(form) // not JSON-stringified
    expect((opts.headers as Record<string, string>)['Content-Type']).toBeUndefined()
    expect((opts.headers as Record<string, string>)['Authorization']).toBe('Bearer tok-123')
  })

  it('returns the parsed payload as { data, status }', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => okJson({ entries: [1, 2] })))
    const { data, status } = await api.get<{ entries: number[] }>('/api/branding/library')
    expect(status).toBe(200)
    expect(data.entries).toEqual([1, 2])
  })
})
