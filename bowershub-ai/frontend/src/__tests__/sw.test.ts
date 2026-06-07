/**
 * Service worker tests — covers the Web Share Target flow declared in
 * `manifest.json` (R9.6, R9.7) and implemented in `public/sw.js`.
 *
 * sw.js is plain JS (not a module) and runs in a ServiceWorkerGlobalScope.
 * To exercise it from a vitest jsdom environment we:
 *   1. Read the file from disk.
 *   2. Wrap it in `new Function('self', code)` so top-level references to
 *      `self.addEventListener`, `self.skipWaiting`, `self.clients` resolve
 *      against a fake we control. `setTimeout`, `Math`, `URL`, `Response`
 *      stay as the jsdom/Node globals.
 *   3. Capture the registered handlers and drive them with synthetic
 *      events.
 *
 * The point isn't to redo end-to-end browser testing — it's to lock in
 * the contract between the manifest's `share_target.action` and the SW's
 * fetch handler, plus the postMessage handshake the SPA's
 * `QuickCapturePage` relies on.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const SW_PATH = path.resolve(__dirname, '../../public/sw.js')
const MANIFEST_PATH = path.resolve(__dirname, '../../public/manifest.json')

type Handler = (ev: any) => any

interface FakeSelf {
  _handlers: Record<string, Handler[]>
  addEventListener(type: string, handler: Handler): void
  skipWaiting: () => void
  clients: { claim: () => Promise<void> }
}

function loadServiceWorker(): FakeSelf {
  const code = fs.readFileSync(SW_PATH, 'utf8')

  const fakeSelf: FakeSelf = {
    _handlers: {},
    addEventListener(type, handler) {
      if (!this._handlers[type]) this._handlers[type] = []
      this._handlers[type].push(handler)
    },
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn(() => Promise.resolve()) },
  }

  // sw.js's activate handler clears caches via `caches.keys()`. jsdom
  // doesn't provide CacheStorage; stub the minimum surface area used.
  ;(globalThis as any).caches = {
    keys: () => Promise.resolve([]),
    delete: () => Promise.resolve(true),
  }

  // Browsers allow `Response.redirect("/relative/path", 303)`, resolving
  // the URL against the request that triggered the SW. Node's undici
  // (used by jsdom) requires an absolute URL and throws otherwise. Stub
  // it with a relative-aware shim so the SW behaves as it would in
  // Chrome.
  const FakeResponse = {
    redirect(url: string, status = 302) {
      return new Response(null, {
        status,
        headers: { Location: url },
      })
    },
  } as unknown as typeof Response
  ;(globalThis as any).Response.redirect = FakeResponse.redirect

  // Exercise sw.js against the fake `self`. Top-level vars
  // (_sharedPayloads, _makeShareToken, SHARE_TARGET_URL) become locals
  // closed over by the registered handlers.
  // eslint-disable-next-line no-new-func
  new Function('self', code)(fakeSelf)

  return fakeSelf
}

function fakeRequest(opts: {
  method: string
  url: string
  form?: Record<string, any>
  files?: { name: string; type: string; buffer: ArrayBuffer }[]
}) {
  const formGet = (key: string) =>
    opts.form && Object.prototype.hasOwnProperty.call(opts.form, key)
      ? opts.form[key]
      : ''
  const formGetAll = (key: string) => {
    if (key === 'files' && opts.files) {
      return opts.files.map(f => ({
        name: f.name,
        type: f.type,
        size: f.buffer.byteLength,
        arrayBuffer: () => Promise.resolve(f.buffer),
      }))
    }
    return []
  }
  return {
    method: opts.method,
    url: opts.url,
    formData: async () => ({ get: formGet, getAll: formGetAll }),
  }
}

async function dispatchFetch(sw: FakeSelf, request: any): Promise<Response | undefined> {
  const handlers = sw._handlers['fetch'] ?? []
  let captured: Promise<Response> | undefined
  const event = {
    request,
    respondWith(p: Promise<Response>) {
      captured = p
    },
  }
  for (const h of handlers) h(event)
  return captured ? await captured : undefined
}

function dispatchMessage(
  sw: FakeSelf,
  data: any,
  opts: { withPort?: boolean } = {},
): { reply: any | null; portReply: any | null } {
  const handlers = sw._handlers['message'] ?? []
  let portReply: any = null
  let reply: any = null

  const port = opts.withPort
    ? { postMessage: (m: any) => (portReply = m) }
    : undefined

  const source = !opts.withPort
    ? { postMessage: (m: any) => (reply = m) }
    : undefined

  const event = { data, ports: port ? [port] : undefined, source }
  for (const h of handlers) h(event)
  return { reply, portReply }
}

describe('manifest.json — Web Share Target (R9.6, R9.7)', () => {
  it('declares versioned icon srcs (R2.4) — handled by backend', () => {
    const raw = fs.readFileSync(MANIFEST_PATH, 'utf8')
    const m = JSON.parse(raw)
    // Static manifest carries unversioned icon paths; the backend
    // (`backend/main.py` /manifest.json handler) appends ?v=<version>.
    expect(Array.isArray(m.icons)).toBe(true)
    expect(m.icons.length).toBeGreaterThanOrEqual(3)
    for (const icon of m.icons) {
      expect(icon.src.startsWith('/icons/')).toBe(true)
    }
  })

  it('declares share_target with action /quick-capture and POST + multipart', () => {
    const m = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'))
    expect(m.share_target).toBeTruthy()
    expect(m.share_target.action).toBe('/quick-capture')
    expect(m.share_target.method).toBe('POST')
    expect(m.share_target.enctype).toBe('multipart/form-data')
    // SPA-side QuickCapturePage reads these param names — keep aligned.
    expect(m.share_target.params.title).toBe('title')
    expect(m.share_target.params.text).toBe('text')
    expect(m.share_target.params.url).toBe('url')
    expect(Array.isArray(m.share_target.params.files)).toBe(true)
    expect(m.share_target.params.files[0].name).toBe('files')
  })
})

describe('sw.js — fetch handler', () => {
  let sw: FakeSelf
  beforeEach(() => {
    sw = loadServiceWorker()
  })

  it('intercepts POST /quick-capture and 303-redirects to /quick-capture?share=<token>', async () => {
    const request = fakeRequest({
      method: 'POST',
      url: 'https://example.com/quick-capture',
      form: { title: 'T', text: 'X', url: 'https://shared.example.com' },
    })

    const res = await dispatchFetch(sw, request)
    expect(res).toBeDefined()
    expect(res!.status).toBe(303)
    const location = res!.headers.get('Location') ?? ''
    expect(location.startsWith('/quick-capture?share=')).toBe(true)
    expect(location.length).toBeGreaterThan('/quick-capture?share='.length)
  })

  it('does not intercept GET requests to /quick-capture (SPA routing)', async () => {
    const request = fakeRequest({
      method: 'GET',
      url: 'https://example.com/quick-capture?share=abc',
    })
    // The SW handler installs `event.respondWith(fetch(request))` for
    // GETs — we just confirm it does *not* return a redirect Response.
    // To avoid a real network call, swap fetch out for a stub.
    const fetchSpy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response('ok', { status: 200 }),
    )
    const res = await dispatchFetch(sw, request)
    expect(res).toBeDefined()
    expect(res!.status).toBe(200)
    expect(fetchSpy).toHaveBeenCalled()
    fetchSpy.mockRestore()
  })

  it('does not intercept POSTs to other paths', async () => {
    const request = fakeRequest({
      method: 'POST',
      url: 'https://example.com/api/something',
    })
    // Non-/quick-capture POSTs fall through (SW has no respondWith for
    // them), so the captured response is undefined.
    const res = await dispatchFetch(sw, request)
    expect(res).toBeUndefined()
  })
})

describe('sw.js — share-target:claim handshake', () => {
  let sw: FakeSelf
  beforeEach(() => {
    sw = loadServiceWorker()
  })

  it('replies with the stashed payload over MessageChannel ports[0]', async () => {
    // Step 1: drive a share-target POST to populate the slot.
    const request = fakeRequest({
      method: 'POST',
      url: 'https://example.com/quick-capture',
      form: { title: 'Hello', text: 'World', url: '' },
      files: [
        { name: 'pic.png', type: 'image/png', buffer: new ArrayBuffer(4) },
      ],
    })
    const res = await dispatchFetch(sw, request)
    const token = new URL(res!.headers.get('Location')!, 'https://example.com')
      .searchParams.get('share')!
    expect(token).toBeTruthy()

    // Step 2: claim the payload via postMessage with a port.
    const { portReply } = dispatchMessage(
      sw,
      { type: 'share-target:claim', token },
      { withPort: true },
    )
    expect(portReply).toBeTruthy()
    expect(portReply.ok).toBe(true)
    expect(portReply.payload.title).toBe('Hello')
    expect(portReply.payload.text).toBe('World')
    expect(portReply.payload.files).toHaveLength(1)
    expect(portReply.payload.files[0].name).toBe('pic.png')
    expect(portReply.payload.files[0].type).toBe('image/png')

    // Step 3: a second claim with the same token should report no
    // payload (one-shot eviction).
    const { portReply: second } = dispatchMessage(
      sw,
      { type: 'share-target:claim', token },
      { withPort: true },
    )
    expect(second.ok).toBe(false)
    expect(second.payload).toBeNull()
  })

  it('falls back to event.source.postMessage when no port is provided', async () => {
    const request = fakeRequest({
      method: 'POST',
      url: 'https://example.com/quick-capture',
      form: { text: 'fallback' },
    })
    const res = await dispatchFetch(sw, request)
    const token = new URL(res!.headers.get('Location')!, 'https://example.com')
      .searchParams.get('share')!

    const { reply } = dispatchMessage(
      sw,
      { type: 'share-target:claim', token },
      { withPort: false },
    )
    expect(reply).toBeTruthy()
    expect(reply.type).toBe('share-target:payload')
    expect(reply.token).toBe(token)
    expect(reply.ok).toBe(true)
    expect(reply.payload.text).toBe('fallback')
  })

  it('returns ok:false for unknown tokens', () => {
    const { portReply } = dispatchMessage(
      sw,
      { type: 'share-target:claim', token: 'never-issued' },
      { withPort: true },
    )
    expect(portReply.ok).toBe(false)
    expect(portReply.payload).toBeNull()
  })

  it('ignores message events with the wrong shape', () => {
    // Empty data, wrong type, missing token — none of these should
    // crash or produce a reply.
    expect(() => dispatchMessage(sw, null)).not.toThrow()
    expect(() => dispatchMessage(sw, { type: 'unrelated' })).not.toThrow()
    expect(() =>
      dispatchMessage(sw, { type: 'share-target:claim' /* no token */ }),
    ).not.toThrow()
  })
})
