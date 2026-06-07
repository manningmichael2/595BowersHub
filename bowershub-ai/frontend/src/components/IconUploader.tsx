/**
 * IconUploader — Admin Console → Icon Management.
 *
 * Implements task 21.1:
 *   - Renders the current 192px and 512px icons side-by-side from
 *     `useBrandingStore().urls`. Versioned URLs (`?v=<ts>`) come from
 *     the backend so reloads pick up fresh images without a hard refresh.
 *   - Upload control: file picker that validates client-side (PNG MIME,
 *     ≥512px square within 1% tolerance, ≤4 MB) BEFORE doing the POST.
 *     Server-side validation in `branding_store.validate_icon` is the
 *     source of truth — this is just a fast-fail UX layer.
 *   - "Revert to default" button → POST /api/branding/icon/revert-to-default.
 *   - "Rollback" button → POST /api/branding/icon/rollback. Disabled
 *     when `!hasRollback`.
 *   - On any successful action, calls `useBrandingStore().refresh()` so
 *     the new manifest version propagates to the rest of the app. The
 *     existing PWA service worker handles cache-busting via the
 *     versioned URLs in manifest.json — no extra registration plumbing
 *     needed here.
 *
 * Validation rules mirror `branding_store.validate_icon`:
 *   - mime == 'image/png'
 *   - min(width, height) >= 512
 *   - abs(width - height) / max(width, height) <= 0.01  (square within 1%)
 *   - size_bytes <= 4 * 1024 * 1024  (4 MB)
 *
 * _Requirements: R2.1, R2.2, R2.3, R2.6, R2.7
 */
import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '../stores/auth'
import { useBrandingStore } from '../stores/branding'

// ---- Constants ------------------------------------------------------------

const MAX_BYTES = 4 * 1024 * 1024 // 4 MB (R2.3)
const MIN_DIMENSION = 512 // px (R2.3)
const SQUARE_TOLERANCE = 0.01 // within 1% (R2.3)
const ACCEPTED_MIME = 'image/png'

// ---- Types ----------------------------------------------------------------

interface ValidationResult {
  ok: boolean
  errors: string[]
  width?: number
  height?: number
}

// ---- Helpers --------------------------------------------------------------

/**
 * Read the image's intrinsic dimensions via the browser's Image API.
 * Resolves with `{width, height}` or rejects if the file isn't decodable.
 */
function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const dims = { width: img.naturalWidth, height: img.naturalHeight }
      URL.revokeObjectURL(url)
      resolve(dims)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Could not decode image'))
    }
    img.src = url
  })
}

async function validateIconFile(file: File): Promise<ValidationResult> {
  const errors: string[] = []

  // MIME (R2.3): file.type is set by the browser from the file's actual
  // header on most platforms; fall back to a name check just in case.
  const mimeOk =
    file.type === ACCEPTED_MIME ||
    (!file.type && file.name.toLowerCase().endsWith('.png'))
  if (!mimeOk) {
    errors.push(`File must be a PNG (got ${file.type || 'unknown'}).`)
  }

  // Size (R2.3)
  if (file.size > MAX_BYTES) {
    const mb = (file.size / 1024 / 1024).toFixed(2)
    errors.push(`File is ${mb} MB; max is 4 MB.`)
  }

  // Dimensions + square tolerance (R2.3) — only attempt if MIME passed,
  // otherwise the decoder may throw on non-PNG content.
  let width: number | undefined
  let height: number | undefined
  if (mimeOk) {
    try {
      const dims = await readImageDimensions(file)
      width = dims.width
      height = dims.height
      if (Math.min(width, height) < MIN_DIMENSION) {
        errors.push(
          `Image is ${width}×${height}px; minimum is ${MIN_DIMENSION}×${MIN_DIMENSION}px.`,
        )
      }
      const ratio = Math.abs(width - height) / Math.max(width, height)
      if (ratio > SQUARE_TOLERANCE) {
        errors.push(
          `Image must be square within 1% (got ${width}×${height}, ${(ratio * 100).toFixed(2)}% off).`,
        )
      }
    } catch {
      errors.push('Could not read image dimensions; the file may be corrupt.')
    }
  }

  return { ok: errors.length === 0, errors, width, height }
}

/**
 * POST the validated PNG to the backend as multipart/form-data.
 * Uses fetch directly because the shared `api` client only handles JSON
 * bodies. Auth token is pulled from the same store the api client uses.
 */
async function uploadIconRequest(file: File): Promise<void> {
  const token = useAuthStore.getState().accessToken
  const formData = new FormData()
  formData.append('file', file)

  const headers: Record<string, string> = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  const res = await fetch('/api/branding/icon', {
    method: 'POST',
    headers,
    body: formData,
  })

  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: 'Upload failed' }))
    const detail = data?.detail
    let msg = 'Upload failed.'
    if (typeof detail === 'string') {
      msg = detail
    } else if (detail?.errors && Array.isArray(detail.errors)) {
      msg = detail.errors.map((e: any) => e.message || String(e)).join(' ')
    }
    throw new Error(msg)
  }
}

async function postJson(path: string): Promise<void> {
  const token = useAuthStore.getState().accessToken
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }
  if (token) headers['Authorization'] = `Bearer ${token}`
  const res = await fetch(path, { method: 'POST', headers })
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: 'Request failed' }))
    const detail = data?.detail
    throw new Error(typeof detail === 'string' ? detail : 'Request failed.')
  }
}

// ---- Component ------------------------------------------------------------

export default function IconUploader() {
  const urls = useBrandingStore(s => s.urls)
  const version = useBrandingStore(s => s.version)
  const hasRollback = useBrandingStore(s => s.hasRollback)
  const isLoading = useBrandingStore(s => s.isLoading)
  const refresh = useBrandingStore(s => s.refresh)

  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [busyAction, setBusyAction] = useState<
    null | 'upload' | 'revert' | 'rollback'
  >(null)
  const [errors, setErrors] = useState<string[]>([])
  const [successMsg, setSuccessMsg] = useState<string | null>(null)

  // Initial load — pulls active manifest into the store.
  useEffect(() => {
    if (urls == null && !isLoading) {
      refresh()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const clearMessages = () => {
    setErrors([])
    setSuccessMsg(null)
  }

  const onPickFile = () => {
    clearMessages()
    fileInputRef.current?.click()
  }

  const onFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    // Reset so re-selecting the same file fires the change event.
    e.target.value = ''
    if (!file) return

    clearMessages()
    const result = await validateIconFile(file)
    if (!result.ok) {
      setErrors(result.errors)
      return
    }

    setBusyAction('upload')
    try {
      await uploadIconRequest(file)
      await refresh()
      setSuccessMsg(
        `Uploaded new icon (${result.width}×${result.height}). Installed PWAs will pick it up on next launch.`,
      )
    } catch (err: any) {
      setErrors([err?.message || 'Upload failed.'])
    } finally {
      setBusyAction(null)
    }
  }

  const onRevertToDefault = async () => {
    clearMessages()
    if (
      !window.confirm(
        'Revert the app icon to the built-in default? The previous icon will remain available via Rollback.',
      )
    ) {
      return
    }
    setBusyAction('revert')
    try {
      await postJson('/api/branding/icon/revert-to-default')
      await refresh()
      setSuccessMsg('Reverted to default icon.')
    } catch (err: any) {
      setErrors([err?.message || 'Revert failed.'])
    } finally {
      setBusyAction(null)
    }
  }

  const onRollback = async () => {
    clearMessages()
    if (
      !window.confirm(
        'Roll back to the previous icon? The current active icon will move into the rollback slot.',
      )
    ) {
      return
    }
    setBusyAction('rollback')
    try {
      await postJson('/api/branding/icon/rollback')
      await refresh()
      setSuccessMsg('Rolled back to previous icon.')
    } catch (err: any) {
      setErrors([err?.message || 'Rollback failed.'])
    } finally {
      setBusyAction(null)
    }
  }

  // ---- Render ------------------------------------------------------------

  const isBusy = busyAction !== null

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-medium text-gray-100">App Icon</h2>
        <p className="text-sm text-gray-400 mt-1">
          The icon shown in the PWA install, browser tab, and home screen.
          Uploads replace all sizes (192px, 512px, maskable-512px) at once.
        </p>
      </div>

      {/* ---- Current icon previews ---- */}
      <section>
        <h3 className="text-sm font-medium text-gray-200 mb-3">Current icon</h3>
        {isLoading && urls == null ? (
          <div className="flex gap-6">
            <div className="h-32 w-32 rounded-lg border border-gray-700 bg-gray-800/30 animate-pulse" />
            <div className="h-32 w-32 rounded-lg border border-gray-700 bg-gray-800/30 animate-pulse" />
          </div>
        ) : urls ? (
          <div className="flex flex-wrap gap-6">
            <IconPreview
              label="192 × 192"
              src={urls.icon_192}
              size={96}
              version={version}
            />
            <IconPreview
              label="512 × 512"
              src={urls.icon_512}
              size={128}
              version={version}
            />
          </div>
        ) : (
          <div className="text-sm text-gray-500 italic">
            No icon manifest available.
          </div>
        )}
        {version && (
          <p className="text-[11px] text-gray-500 mt-2">
            Manifest version: <code className="text-gray-400">{version}</code>
          </p>
        )}
      </section>

      {/* ---- Messages ---- */}
      {errors.length > 0 && (
        <div className="rounded-lg border border-red-700/40 bg-red-900/20 px-3 py-2 text-sm text-red-300 space-y-1">
          {errors.map((err, i) => (
            <div key={i}>{err}</div>
          ))}
        </div>
      )}
      {successMsg && (
        <div className="rounded-lg border border-emerald-700/40 bg-emerald-900/20 px-3 py-2 text-sm text-emerald-300">
          {successMsg}
        </div>
      )}

      {/* ---- Actions ---- */}
      <section className="space-y-3">
        <h3 className="text-sm font-medium text-gray-200">Actions</h3>

        <input
          ref={fileInputRef}
          type="file"
          accept="image/png"
          className="hidden"
          onChange={onFileSelected}
        />

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onPickFile}
            disabled={isBusy}
            className="px-3 py-1.5 rounded-lg bg-indigo-600 text-sm text-white hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed"
          >
            {busyAction === 'upload' ? 'Uploading…' : '⬆ Upload new icon'}
          </button>

          <button
            type="button"
            onClick={onRevertToDefault}
            disabled={isBusy}
            className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            title="Restore the built-in default icon"
          >
            {busyAction === 'revert' ? 'Reverting…' : '↺ Revert to default'}
          </button>

          <button
            type="button"
            onClick={onRollback}
            disabled={isBusy || !hasRollback}
            className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300 hover:bg-gray-700 disabled:opacity-40 disabled:cursor-not-allowed"
            title={
              hasRollback
                ? 'Swap back to the previous icon'
                : 'No previous icon stored'
            }
          >
            {busyAction === 'rollback' ? 'Rolling back…' : '⤺ Rollback'}
          </button>
        </div>

        <p className="text-xs text-gray-500">
          Required: PNG, square (within 1%), at least 512×512px, ≤ 4 MB. The
          server will generate the 192px and maskable-512px variants.
        </p>
      </section>
    </div>
  )
}

// ---- Sub-components -------------------------------------------------------

function IconPreview({
  label,
  src,
  size,
  version,
}: {
  label: string
  src: string
  size: number
  version: string | null
}) {
  // Append the manifest version as a query string so the browser refetches
  // after a swap. The backend already includes its own `?v=` in `urls`, but
  // we add an extra layer here so React's render-key reflects the version
  // change too — guarantees the <img> reloads instead of using a cached
  // resource keyed only on URL.
  const versioned = version
    ? `${src}${src.includes('?') ? '&' : '?'}cb=${version}`
    : src
  return (
    <div className="flex flex-col items-center gap-2">
      <div
        className="rounded-lg border border-gray-700 bg-gray-900/60 p-2"
        style={{ width: size + 16, height: size + 16 }}
      >
        <img
          src={versioned}
          alt={`App icon ${label}`}
          width={size}
          height={size}
          className="rounded"
          style={{ width: size, height: size, objectFit: 'contain' }}
        />
      </div>
      <span className="text-[11px] text-gray-500">{label}</span>
    </div>
  )
}
