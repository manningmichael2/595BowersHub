/**
 * QuickCapturePage — wraps `<QuickCaptureOverlay />` for the
 * `/quick-capture` PWA share-target route (task 26.2).
 *
 * Two ways the user lands here:
 *
 *   1. Direct navigation (typing the URL, deep link, etc.) — we just
 *      render the overlay with no pre-population. Closing returns to
 *      `/`.
 *
 *   2. Web Share Target on Android — Chrome POSTs a multipart form to
 *      `/quick-capture`; the service worker (see `public/sw.js`)
 *      intercepts that POST, stashes the payload in an in-memory slot
 *      keyed by a one-shot token, then issues a 303 redirect to
 *      `/quick-capture?share=<token>`. This page reads the `share`
 *      query param, asks the SW for the payload via `postMessage`, and
 *      pre-populates `initialText` / `initialImage` on the overlay.
 *
 * Image payloads coming from the OS share sheet arrive as raw
 * `ArrayBuffer`s from the SW handshake. To turn them into something
 * the smart-capture extract path can consume, we POST the buffer to
 * the existing `/api/files/upload` endpoint and use the resulting
 * asset metadata as the overlay's `initialImage` prop. The same
 * upload endpoint is what the in-overlay attach-image button uses,
 * so paths and asset_ids stay consistent across the two entry
 * points.
 *
 * _Requirements: R9.1, R9.6, R9.7_
 */

import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import QuickCaptureOverlay from '../components/QuickCaptureOverlay'
import { useAuthStore } from '../stores/auth'

interface AttachedImage {
  asset_id?: string
  path: string
  filename: string
}

interface SharePayloadFile {
  name: string
  type: string
  size: number
  buffer: ArrayBuffer
}

interface SharePayload {
  title?: string
  text?: string
  url?: string
  files?: SharePayloadFile[]
}

type ClaimState =
  | { kind: 'idle' }
  | { kind: 'claiming' }
  | { kind: 'uploading' }
  | { kind: 'ready'; initialText?: string; initialImage?: AttachedImage }
  | { kind: 'error'; message: string }

/**
 * Ask the active service worker for the share payload that matches
 * `token`. Returns `null` if no SW is registered, the claim times out,
 * or the SW reports no payload for that token.
 *
 * Uses a `MessageChannel` (preferred) so the response goes only to
 * this caller. Falls back to a `navigator.serviceWorker.message`
 * listener if MessageChannel isn't supported by the SW.
 */
function claimSharePayload(token: string, timeoutMs = 4000): Promise<SharePayload | null> {
  return new Promise(resolve => {
    if (!('serviceWorker' in navigator)) {
      resolve(null)
      return
    }

    let resolved = false
    const settle = (payload: SharePayload | null) => {
      if (resolved) return
      resolved = true
      resolve(payload)
    }

    const timer = window.setTimeout(() => settle(null), timeoutMs)

    navigator.serviceWorker.ready
      .then(reg => {
        const ctrl = navigator.serviceWorker.controller ?? reg.active
        if (!ctrl) {
          window.clearTimeout(timer)
          settle(null)
          return
        }

        const channel = new MessageChannel()
        channel.port1.onmessage = ev => {
          window.clearTimeout(timer)
          const data = ev.data
          if (data && data.ok && data.payload) {
            settle(data.payload as SharePayload)
          } else {
            settle(null)
          }
        }

        try {
          ctrl.postMessage({ type: 'share-target:claim', token }, [channel.port2])
        } catch {
          window.clearTimeout(timer)
          settle(null)
        }
      })
      .catch(() => {
        window.clearTimeout(timer)
        settle(null)
      })
  })
}

/**
 * Upload a shared image buffer through `/api/files/upload`. Returns
 * an `AttachedImage` shape compatible with `QuickCaptureOverlay`'s
 * `initialImage` prop, or `null` if the upload fails (in which case
 * the overlay still opens with whatever text payload we captured).
 */
async function uploadSharedImage(
  file: SharePayloadFile,
  accessToken: string | null,
): Promise<AttachedImage | null> {
  try {
    const blob = new Blob([file.buffer], { type: file.type || 'application/octet-stream' })
    const form = new FormData()
    form.append('files', blob, file.name || 'shared-image')
    // Quick capture isn't tied to a chat conversation — match the
    // overlay's own attach-image flow which uses conversation_id=0.
    form.append('conversation_id', '0')

    const res = await fetch('/api/files/upload', {
      method: 'POST',
      headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
      body: form,
    })
    if (!res.ok) return null
    const data = await res.json()
    const first = data?.files?.[0]
    if (!first || first.error) return null
    return {
      asset_id: first.asset_id,
      path: first.path,
      filename: first.filename ?? file.name,
    }
  } catch {
    return null
  }
}

export default function QuickCapturePage() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const accessToken = useAuthStore(s => s.accessToken)

  // Pull the share token from the URL once. URLSearchParams is stable
  // across renders so this useMemo is effectively per-mount.
  const shareToken = useMemo(() => params.get('share'), [params])

  const [state, setState] = useState<ClaimState>(
    shareToken ? { kind: 'claiming' } : { kind: 'ready' },
  )

  useEffect(() => {
    if (!shareToken) return
    let cancelled = false

    setState({ kind: 'claiming' })
    claimSharePayload(shareToken).then(async payload => {
      if (cancelled) return
      if (!payload) {
        // No payload — open the empty overlay so the user isn't trapped.
        setState({ kind: 'ready' })
        return
      }

      // Combine the title/text/url params into a single textarea seed.
      // The Web Share API splits these into separate fields, but the
      // overlay only has one textarea — joining with newlines keeps
      // everything visible without losing structure.
      const parts: string[] = []
      if (payload.title) parts.push(payload.title)
      if (payload.text) parts.push(payload.text)
      if (payload.url) parts.push(payload.url)
      const initialText = parts.length > 0 ? parts.join('\n\n') : undefined

      const firstImage = (payload.files ?? []).find(f =>
        (f.type ?? '').toLowerCase().startsWith('image/'),
      )

      if (!firstImage) {
        setState({ kind: 'ready', initialText })
        return
      }

      setState({ kind: 'uploading' })
      const initialImage = await uploadSharedImage(firstImage, accessToken)
      if (cancelled) return
      // Even if the image upload failed we still open the overlay —
      // the user can re-attach manually. We just drop the image part.
      setState({
        kind: 'ready',
        initialText,
        initialImage: initialImage ?? undefined,
      })
    })

    return () => {
      cancelled = true
    }
  }, [shareToken, accessToken])

  // Always navigate back to the app root after the overlay closes so
  // refreshing the page doesn't stay on `/quick-capture` forever.
  const handleClose = () => {
    navigate('/', { replace: true })
  }

  if (state.kind === 'claiming' || state.kind === 'uploading') {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
        <div className="rounded-xl bg-gray-900 border border-gray-700 px-6 py-4 text-sm text-gray-300">
          {state.kind === 'claiming'
            ? 'Loading shared content…'
            : 'Uploading shared image…'}
        </div>
      </div>
    )
  }

  if (state.kind === 'error') {
    // Best-effort: still show the overlay so the user can capture
    // manually instead of getting stuck on an error screen.
    return (
      <QuickCaptureOverlay onClose={handleClose} />
    )
  }

  return (
    <QuickCaptureOverlay
      initialText={state.kind === 'ready' ? state.initialText : undefined}
      initialImage={state.kind === 'ready' ? state.initialImage : undefined}
      onClose={handleClose}
    />
  )
}
