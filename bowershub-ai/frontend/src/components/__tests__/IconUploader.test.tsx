/**
 * Component tests for `IconUploader`.
 *
 * Covers task 21.2:
 *   1. Upload of a non-PNG file → client-side rejection with a descriptive
 *      message; no POST to `/api/branding/icon` happens.
 *   2. Upload of a 511px PNG (one pixel below the 512px minimum) → client-side
 *      rejection with a min-dimension message; no POST.
 *   3. Successful upload of a 1024×1024 PNG → POST is fired, the branding
 *      store's `refresh()` runs and pulls a new manifest version, and a
 *      success message appears in the UI.
 *
 * Mocking strategy:
 *   - `useBrandingStore` and `useAuthStore` are seeded directly via their
 *     `setState` APIs rather than module-mocked. Same pattern as
 *     `stores/__tests__/settings.test.ts` — keeps the component wired to
 *     the real Zustand stores so the post-upload `refresh()` call truly
 *     updates the version visible to the component.
 *   - `Image` is replaced with a fake that synchronously sets configured
 *     `naturalWidth` / `naturalHeight` and fires `onload` on the next
 *     microtask. This drives `readImageDimensions` inside the component
 *     without needing real PNG decoding (jsdom can't decode binary PNGs).
 *   - `URL.createObjectURL` / `revokeObjectURL` are stubbed because jsdom's
 *     implementations require a real Blob registry.
 *   - `fetch` is mocked per-test using `vi.spyOn(global, 'fetch')`. The
 *     upload path POSTs to `/api/branding/icon`; the subsequent refresh
 *     does a GET on the same path — the mock dispatches by method.
 *
 * _Requirements: R2.3 (PNG / dimension / size validation), R2.2 (upload pipeline)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import IconUploader from '../IconUploader'
import { useBrandingStore, type BrandingUrls } from '../../stores/branding'
import { useAuthStore } from '../../stores/auth'

// ------------------------------------------------------------------
// Mock Image — drives `readImageDimensions` inside the component
// ------------------------------------------------------------------

let mockImageDimensions = { width: 1024, height: 1024 }
let mockImageBehavior: 'load' | 'error' = 'load'

class MockImage {
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  naturalWidth = 0
  naturalHeight = 0
  // Setting `src` is what kicks off the fake decode. We populate dimensions
  // synchronously and fire the callback on the next microtask so the awaited
  // promise inside `readImageDimensions` resolves naturally.
  set src(_value: string) {
    this.naturalWidth = mockImageDimensions.width
    this.naturalHeight = mockImageDimensions.height
    queueMicrotask(() => {
      if (mockImageBehavior === 'load') this.onload?.()
      else this.onerror?.()
    })
  }
}

// ------------------------------------------------------------------
// File / fetch helpers
// ------------------------------------------------------------------

function makeFile(name: string, mime: string, sizeBytes = 1024): File {
  // Build the file from a real Uint8Array so `file.size` reflects reality
  // without redefining the property (which jsdom resists).
  const data = new Uint8Array(sizeBytes)
  return new File([data], name, { type: mime })
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const INITIAL_URLS: BrandingUrls = {
  icon_192: '/icons/icon-192.png?v=v1',
  icon_512: '/icons/icon-512.png?v=v1',
  icon_maskable_512: '/icons/icon-maskable-512.png?v=v1',
}

const REFRESHED_URLS: BrandingUrls = {
  icon_192: '/icons/icon-192.png?v=v2',
  icon_512: '/icons/icon-512.png?v=v2',
  icon_maskable_512: '/icons/icon-maskable-512.png?v=v2',
}

// ------------------------------------------------------------------
// Lifecycle
// ------------------------------------------------------------------

beforeEach(() => {
  vi.stubGlobal('Image', MockImage as unknown as typeof Image)
  ;(URL as any).createObjectURL = vi.fn(() => 'blob:mock-url')
  ;(URL as any).revokeObjectURL = vi.fn()

  // Reset fake-image defaults
  mockImageDimensions = { width: 1024, height: 1024 }
  mockImageBehavior = 'load'

  // Seed the branding store with a known starting state. Crucially, `urls`
  // is NOT null so the component's mount-time `refresh()` won't fire and
  // pollute the fetch mock.
  useBrandingStore.setState({
    version: 'v1',
    urls: INITIAL_URLS,
    hasRollback: false,
    isLoading: false,
  })

  // Seed the auth store with an access token so the upload POST gets one.
  useAuthStore.setState({
    user: null,
    accessToken: 'test-bearer-token',
    refreshToken: null,
    isLoading: false,
    error: null,
    isRefreshing: false,
  } as any)
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

// ------------------------------------------------------------------
// Tests
// ------------------------------------------------------------------

describe('IconUploader — client-side validation', () => {
  it('rejects a non-PNG file with a descriptive message and skips the POST', async () => {
    const fetchMock = vi.spyOn(global, 'fetch')

    const { container } = render(<IconUploader />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement
    expect(input).toBeTruthy()

    const jpegFile = makeFile('logo.jpg', 'image/jpeg', 50_000)
    fireEvent.change(input, { target: { files: [jpegFile] } })

    // Error banner is rendered with a "PNG" complaint.
    const err = await screen.findByText(/must be a PNG/i)
    expect(err).toBeTruthy()

    // No backend call happened — pure client-side rejection.
    expect(fetchMock).not.toHaveBeenCalled()
    // Version is unchanged.
    expect(useBrandingStore.getState().version).toBe('v1')
  })

  it('rejects a 511px PNG (one pixel below the minimum) with a min-dimension message', async () => {
    mockImageDimensions = { width: 511, height: 511 }
    const fetchMock = vi.spyOn(global, 'fetch')

    const { container } = render(<IconUploader />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement

    const tinyPng = makeFile('icon.png', 'image/png', 50_000)
    fireEvent.change(input, { target: { files: [tinyPng] } })

    // Component formats the dim message as "minimum is 512×512px"
    const err = await screen.findByText(/minimum is 512.{0,5}512/i)
    expect(err).toBeTruthy()

    expect(fetchMock).not.toHaveBeenCalled()
    expect(useBrandingStore.getState().version).toBe('v1')
  })
})

describe('IconUploader — successful upload', () => {
  it('POSTs the file, refreshes the manifest, and reflects the new version', async () => {
    mockImageDimensions = { width: 1024, height: 1024 }

    // Track POST + GET separately so we can assert both fired.
    let sawUploadPost = false
    let sawRefreshGet = false

    const fetchMock = vi
      .spyOn(global, 'fetch')
      .mockImplementation(async (input, init) => {
        const url =
          typeof input === 'string'
            ? input
            : input instanceof URL
              ? input.toString()
              : (input as Request).url
        const method = (init?.method || 'GET').toUpperCase()

        if (url.endsWith('/api/branding/icon') && method === 'POST') {
          sawUploadPost = true
          return jsonResponse({ version: 'v2', urls: REFRESHED_URLS })
        }
        if (url.endsWith('/api/branding/icon') && method === 'GET') {
          sawRefreshGet = true
          return jsonResponse({
            version: 'v2',
            urls: REFRESHED_URLS,
            has_rollback: true,
          })
        }
        return new Response('not found', { status: 404 })
      })

    const { container } = render(<IconUploader />)
    const input = container.querySelector('input[type="file"]') as HTMLInputElement

    const goodPng = makeFile('icon.png', 'image/png', 200_000)
    fireEvent.change(input, { target: { files: [goodPng] } })

    // Wait for the upload + refresh chain to complete (success banner is
    // the last thing the handler does).
    await screen.findByText(/Uploaded new icon/i)

    // Both calls must have fired (POST upload, then GET refresh).
    expect(sawUploadPost).toBe(true)
    expect(sawRefreshGet).toBe(true)

    // Branding store reflects the new manifest version + rollback slot.
    await waitFor(() => {
      const branding = useBrandingStore.getState()
      expect(branding.version).toBe('v2')
      expect(branding.hasRollback).toBe(true)
      expect(branding.urls).toEqual(REFRESHED_URLS)
    })

    // The POST included the file as multipart/form-data with the bearer token.
    const postCall = fetchMock.mock.calls.find(c => {
      const reqInit = c[1] as RequestInit | undefined
      return (reqInit?.method || '').toUpperCase() === 'POST'
    })
    expect(postCall).toBeTruthy()
    const reqInit = postCall![1] as RequestInit
    expect(reqInit.body).toBeInstanceOf(FormData)
    const headers = reqInit.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer test-bearer-token')
  })
})
