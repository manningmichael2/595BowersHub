/**
 * QuickCaptureOverlay — modal that drives the Quick Capture flow.
 *
 * Implements task 26.1.
 *
 * Flow:
 *   1. Compose view: multi-line textarea + optional image attach +
 *      Save / Cancel buttons.
 *   2. On Save: upload image (if attached), then call
 *      `POST /api/quick-capture/extract`. The upstream skill response
 *      flows back unchanged and includes a list of draft `intents` plus
 *      the `extract_token` we need for the follow-up commit calls.
 *   3. Confirm view: render each intent with a checkbox so the user
 *      can drop ones they don't want before committing. Back returns
 *      to the compose view; Confirm calls
 *      `POST /api/quick-capture/commit` once per accepted intent.
 *   4. Success view: brief summary "Saved N item(s)" before auto-close.
 *
 * Failure paths:
 *   - Extract returns 502 with `retryable: true` → show Retry plus
 *     "Save as raw note" (R9.9). Raw note posts to
 *     `POST /api/quick-capture/raw-note` and bypasses the AI path.
 *   - Commit failure → keep the user on the confirm view with the
 *     error visible so they can re-try the remaining intents.
 *
 * Closing:
 *   - Cancel button or Escape closes the overlay without any backend
 *     calls (R9.5). Clicking the backdrop on desktop also closes; on
 *     mobile the modal is full-screen and the backdrop is unreachable.
 *
 * Props:
 *   - initialText?:  pre-populated text (PWA share target / share intent)
 *   - initialImage?: pre-uploaded image asset metadata (share target)
 *   - workspaceId:   id of the workspace this capture inherits context
 *                    from (R9.8). Falls back to the active workspace.
 *   - onClose:       close-the-overlay callback. Receives an optional
 *                    summary string so the parent can show a toast.
 *
 * Hotkey wiring + the `/quick-capture` PWA route are owned by tasks
 * 26.2 and 26.3 respectively — this component is the inner UI only.
 *
 * _Requirements: R9.1, R9.2, R9.3, R9.4, R9.5, R9.7, R9.8, R9.9
 */

import { useEffect, useRef, useState } from 'react'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'
import { api } from '../services/api'

// ---------------------------------------------------------------------------
// Types — mirror the smart-capture/extract response shape.
// ---------------------------------------------------------------------------

interface CaptureIntent {
  domain: string
  summary: string
  payload: Record<string, unknown>
  needs_more_info?: boolean
}

interface ExtractResponse {
  ok?: boolean
  intents?: CaptureIntent[]
  asset?: { id?: string; path?: string } | null
  raw_text?: string
  extract_token?: string
}

interface AttachedImage {
  /** asset id returned by `/api/files/upload` (used as `asset_id` on commit) */
  asset_id?: string
  /** relative path under FILES_ROOT — what smart-capture/extract expects */
  path: string
  /** original filename for the preview pill */
  filename: string
}

export interface QuickCaptureOverlayProps {
  initialText?: string
  initialImage?: AttachedImage
  workspaceId?: number
  onClose: (summary?: string) => void
}

// ---------------------------------------------------------------------------
// View states
// ---------------------------------------------------------------------------

type ViewState =
  | { kind: 'compose' }
  | { kind: 'extracting' }
  | { kind: 'confirm'; intents: CaptureIntent[]; extract_token: string; assetId?: string }
  | { kind: 'committing' }
  | { kind: 'success'; message: string }
  | { kind: 'extract_error'; message: string; retryable: boolean }
  | { kind: 'raw_saving' }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Extract a friendly error message from the api client's error shape. */
function readErrorMessage(err: any, fallback: string): string {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (detail && typeof detail === 'object') {
    if (typeof detail.message === 'string') return detail.message
    if (typeof detail.error === 'string') return detail.error
  }
  if (typeof err?.message === 'string') return err.message
  return fallback
}

/** Pluralizing helper for the success summary. */
function pluralize(count: number, singular: string, plural?: string): string {
  return `${count} ${count === 1 ? singular : plural ?? `${singular}s`}`
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function QuickCaptureOverlay({
  initialText,
  initialImage,
  workspaceId,
  onClose,
}: QuickCaptureOverlayProps) {
  const user = useAuthStore(s => s.user)
  const activeWorkspace = useWorkspaceStore(s => s.activeWorkspace)

  // R9.8 — inherit workspace context. The prop wins so share-target
  // navigations can target a specific workspace; otherwise fall back
  // to whatever workspace the user is currently in.
  const effectiveWorkspaceId = workspaceId ?? activeWorkspace?.id ?? null

  const [text, setText] = useState(initialText ?? '')
  const [image, setImage] = useState<AttachedImage | null>(initialImage ?? null)
  const [view, setView] = useState<ViewState>({ kind: 'compose' })
  const [accepted, setAccepted] = useState<boolean[]>([])
  const [commitErrors, setCommitErrors] = useState<string[]>([])
  const [uploading, setUploading] = useState(false)

  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // -------------------------------------------------------------------
  // Focus + keyboard handling
  // -------------------------------------------------------------------

  // Focus the textarea on mount so the user can start typing immediately.
  useEffect(() => {
    textareaRef.current?.focus()
  }, [])

  // Escape closes without any backend calls (R9.5).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // -------------------------------------------------------------------
  // Image upload (R9.3)
  // -------------------------------------------------------------------

  const onPickImage = () => {
    fileInputRef.current?.click()
  }

  const onImageSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    // Reset the input value so picking the same file twice still fires.
    e.target.value = ''
    if (!file) return

    setUploading(true)
    try {
      const form = new FormData()
      form.append('files', file)
      // Quick capture isn't tied to a chat conversation; the upload
      // endpoint accepts conversation_id=0 and stores under
      // /files/chat-uploads/0/<uuid>.<ext>.
      form.append('conversation_id', '0')

      const token = useAuthStore.getState().accessToken
      const res = await fetch('/api/files/upload', {
        method: 'POST',
        headers: token ? { Authorization: `Bearer ${token}` } : {},
        body: form,
      })
      if (!res.ok) {
        const detail = await res.json().catch(() => ({}))
        throw new Error(detail?.detail ?? `Upload failed (${res.status})`)
      }
      const data = await res.json()
      const first = data?.files?.[0]
      if (!first || first.error) {
        throw new Error(first?.error ?? 'Upload returned no asset')
      }

      setImage({
        asset_id: first.asset_id,
        path: first.path,
        filename: first.filename ?? file.name,
      })
    } catch (err: any) {
      setView({
        kind: 'extract_error',
        message: readErrorMessage(err, 'Image upload failed'),
        // Image upload errors usually aren't on the smart-capture path,
        // but we still let the user retry the whole thing.
        retryable: true,
      })
    } finally {
      setUploading(false)
    }
  }

  const removeImage = () => setImage(null)

  // -------------------------------------------------------------------
  // Extract (R9.2 / R9.3)
  // -------------------------------------------------------------------

  const runExtract = async () => {
    if (effectiveWorkspaceId == null) {
      setView({
        kind: 'extract_error',
        message: 'No active workspace — choose a workspace before capturing.',
        retryable: false,
      })
      return
    }
    if (!text.trim() && !image) {
      // Should be prevented by the disabled Save button, but guard anyway.
      return
    }

    setView({ kind: 'extracting' })
    setCommitErrors([])
    try {
      const body: Record<string, unknown> = { workspace_id: effectiveWorkspaceId }
      if (text.trim()) body.text = text.trim()
      if (image) body.image_path = image.path

      const res = await api.post('/api/quick-capture/extract', body)
      const data: ExtractResponse = res.data ?? {}
      const intents = Array.isArray(data.intents) ? data.intents : []
      const token = data.extract_token ?? ''

      if (intents.length === 0 || !token) {
        // Smart-capture answered but didn't produce anything actionable
        // — treat as an extract failure so the user gets the raw-note
        // fallback instead of a dead-end confirm view.
        setView({
          kind: 'extract_error',
          message:
            intents.length === 0
              ? 'No intents extracted from this input.'
              : 'Extract response missing the verification token.',
          retryable: true,
        })
        return
      }

      setAccepted(new Array(intents.length).fill(true))
      setView({
        kind: 'confirm',
        intents,
        extract_token: token,
        assetId: image?.asset_id ?? data.asset?.id,
      })
    } catch (err: any) {
      const status = err?.response?.status
      const detail = err?.response?.data?.detail
      // The router returns 502 + {retryable: true} for n8n / smart-capture
      // upstream errors. That's the case where R9.9's "Save as raw note"
      // is most relevant. We still offer it for any error so the user
      // is never trapped without an escape hatch.
      const retryable =
        status === 502 ||
        (detail && typeof detail === 'object' && detail.retryable === true) ||
        true
      setView({
        kind: 'extract_error',
        message: readErrorMessage(err, 'Smart Capture is unavailable.'),
        retryable,
      })
    }
  }

  // -------------------------------------------------------------------
  // Commit (R9.4)
  // -------------------------------------------------------------------

  const runCommit = async () => {
    if (view.kind !== 'confirm') return
    if (effectiveWorkspaceId == null) return
    const { intents, extract_token, assetId } = view

    const acceptedIntents = intents.filter((_, i) => accepted[i])
    if (acceptedIntents.length === 0) {
      // Nothing to commit — treat Confirm as Cancel.
      onClose()
      return
    }

    setView({ kind: 'committing' })
    setCommitErrors([])
    const errors: string[] = []
    let successCount = 0
    const perDomain = new Map<string, number>()

    for (const intent of acceptedIntents) {
      try {
        const body: Record<string, unknown> = {
          domain: intent.domain,
          payload: intent.payload,
          extract_token,
          workspace_id: effectiveWorkspaceId,
        }
        if (assetId) body.asset_id = assetId
        await api.post('/api/quick-capture/commit', body)
        successCount += 1
        perDomain.set(intent.domain, (perDomain.get(intent.domain) ?? 0) + 1)
      } catch (err: any) {
        errors.push(
          `${intent.summary || intent.domain}: ${readErrorMessage(err, 'commit failed')}`,
        )
      }
    }

    if (errors.length > 0) {
      // Re-show the confirm view with the per-intent error list so the
      // user can see which ones failed. Drop the successful ones from
      // the accepted set so a retry doesn't double-write them.
      setCommitErrors(errors)
      const stillPending = intents.map((it, i) => {
        if (!accepted[i]) return false
        // If this intent was committed successfully, untick it.
        const wasCommitted = !errors.some(e =>
          e.startsWith(`${it.summary || it.domain}: `),
        )
        return !wasCommitted
      })
      setAccepted(stillPending)
      setView({ kind: 'confirm', intents, extract_token, assetId })
      return
    }

    // All accepted intents committed. Show a brief success summary then
    // close (R9.4 — single success toast).
    const parts: string[] = []
    for (const [domain, count] of perDomain) {
      parts.push(pluralize(count, prettyDomainName(domain)))
    }
    const message = `Saved ${parts.join(', ')}`
    setView({ kind: 'success', message })
    // Auto-close after a beat so the user gets the visual confirmation.
    window.setTimeout(() => onClose(message), 1200)
  }

  // -------------------------------------------------------------------
  // Raw-note fallback (R9.9)
  // -------------------------------------------------------------------

  const runRawNote = async () => {
    if (effectiveWorkspaceId == null) return
    if (!text.trim()) return
    setView({ kind: 'raw_saving' })
    try {
      await api.post('/api/quick-capture/raw-note', {
        text: text.trim(),
        workspace_id: effectiveWorkspaceId,
      })
      const message = 'Saved as raw note'
      setView({ kind: 'success', message })
      window.setTimeout(() => onClose(message), 1200)
    } catch (err: any) {
      setView({
        kind: 'extract_error',
        message: readErrorMessage(err, 'Failed to save raw note.'),
        retryable: false,
      })
    }
  }

  // -------------------------------------------------------------------
  // Render
  // -------------------------------------------------------------------

  const canSave =
    (text.trim().length > 0 || image !== null) && effectiveWorkspaceId != null

  return (
    <div
      className="fixed inset-0 z-50 flex items-stretch sm:items-center justify-center bg-black/60 backdrop-blur-sm sm:p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="quick-capture-title"
      onClick={e => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="relative flex flex-col w-full sm:max-w-xl bg-gray-900 border border-gray-700 sm:rounded-2xl shadow-2xl max-h-screen sm:max-h-[85vh] overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between gap-3 px-5 py-3 border-b border-gray-700 shrink-0">
          <h2 id="quick-capture-title" className="text-lg font-medium text-gray-100">
            ⚡ Quick Capture
          </h2>
          <div className="flex items-center gap-2">
            <kbd className="hidden sm:inline-block text-[10px] text-gray-500 bg-gray-800 px-1.5 py-0.5 rounded">
              Esc
            </kbd>
            <button
              type="button"
              onClick={() => onClose()}
              className="p-1.5 rounded-lg text-gray-400 hover:bg-gray-800 hover:text-gray-200"
              aria-label="Close"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Body — content depends on the current view */}
        <div className="flex-1 overflow-y-auto p-5">
          {view.kind === 'compose' && (
            <ComposeView
              text={text}
              setText={setText}
              image={image}
              uploading={uploading}
              onPickImage={onPickImage}
              onRemoveImage={removeImage}
              textareaRef={textareaRef}
              workspaceName={activeWorkspace?.name ?? null}
              workspaceId={effectiveWorkspaceId}
            />
          )}

          {view.kind === 'extracting' && (
            <StatusView icon="⏳" title="Extracting…" caption="Asking smart-capture to read your input." />
          )}

          {view.kind === 'confirm' && (
            <ConfirmView
              intents={view.intents}
              accepted={accepted}
              setAccepted={setAccepted}
              commitErrors={commitErrors}
            />
          )}

          {view.kind === 'committing' && (
            <StatusView icon="💾" title="Saving…" caption="Committing accepted captures." />
          )}

          {view.kind === 'raw_saving' && (
            <StatusView icon="📝" title="Saving raw note…" caption="Bypassing the AI pipeline." />
          )}

          {view.kind === 'success' && (
            <StatusView icon="✅" title={view.message} caption="Closing…" />
          )}

          {view.kind === 'extract_error' && (
            <ExtractErrorView
              message={view.message}
              retryable={view.retryable}
              hasText={text.trim().length > 0}
            />
          )}
        </div>

        {/* Footer — buttons depend on view */}
        <div className="flex items-center justify-end gap-2 px-5 py-3 border-t border-gray-700 shrink-0 bg-gray-900/80">
          {view.kind === 'compose' && (
            <>
              <span className="mr-auto text-xs text-gray-500">
                {effectiveWorkspaceId == null
                  ? 'Choose a workspace first'
                  : `Capturing into "${activeWorkspace?.name ?? `workspace ${effectiveWorkspaceId}`}"`}
              </span>
              <button
                type="button"
                onClick={() => onClose()}
                className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300 hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                type="button"
                disabled={!canSave || uploading}
                onClick={runExtract}
                className={
                  'px-4 py-1.5 rounded-lg text-sm font-medium ' +
                  (canSave && !uploading
                    ? 'bg-indigo-600 text-white hover:bg-indigo-500'
                    : 'bg-gray-800 text-gray-500 cursor-not-allowed')
                }
              >
                Save
              </button>
            </>
          )}

          {view.kind === 'confirm' && (
            <>
              <button
                type="button"
                onClick={() => setView({ kind: 'compose' })}
                className="mr-auto px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300 hover:bg-gray-700"
              >
                ← Back
              </button>
              <button
                type="button"
                onClick={() => onClose()}
                className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300 hover:bg-gray-700"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={runCommit}
                disabled={accepted.every(a => !a)}
                className={
                  'px-4 py-1.5 rounded-lg text-sm font-medium ' +
                  (accepted.some(a => a)
                    ? 'bg-indigo-600 text-white hover:bg-indigo-500'
                    : 'bg-gray-800 text-gray-500 cursor-not-allowed')
                }
              >
                Confirm
              </button>
            </>
          )}

          {view.kind === 'extract_error' && (
            <>
              <button
                type="button"
                onClick={() => onClose()}
                className="mr-auto px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-300 hover:bg-gray-700"
              >
                Cancel
              </button>
              {view.retryable && (
                <button
                  type="button"
                  onClick={runExtract}
                  className="px-3 py-1.5 rounded-lg bg-gray-800 text-sm text-gray-200 hover:bg-gray-700"
                >
                  Retry
                </button>
              )}
              <button
                type="button"
                onClick={runRawNote}
                disabled={text.trim().length === 0}
                className={
                  'px-4 py-1.5 rounded-lg text-sm font-medium ' +
                  (text.trim().length > 0
                    ? 'bg-indigo-600 text-white hover:bg-indigo-500'
                    : 'bg-gray-800 text-gray-500 cursor-not-allowed')
                }
                title={
                  text.trim().length === 0
                    ? 'Type some text first to save as a raw note'
                    : 'Append your text verbatim to /knowledge/captures/'
                }
              >
                Save as raw note
              </button>
            </>
          )}
        </div>

        {/* Hidden file input — wired to the attach button. */}
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          onChange={onImageSelected}
          className="hidden"
        />

        {/* Suppress unused-var warning when the build trims `user` */}
        {!user && null}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-views
// ---------------------------------------------------------------------------

function ComposeView({
  text,
  setText,
  image,
  uploading,
  onPickImage,
  onRemoveImage,
  textareaRef,
  workspaceName,
  workspaceId,
}: {
  text: string
  setText: (v: string) => void
  image: AttachedImage | null
  uploading: boolean
  onPickImage: () => void
  onRemoveImage: () => void
  textareaRef: React.RefObject<HTMLTextAreaElement>
  workspaceName: string | null
  workspaceId: number | null
}) {
  return (
    <div className="space-y-3">
      <div>
        <label htmlFor="quick-capture-text" className="sr-only">
          Capture text
        </label>
        <textarea
          ref={textareaRef}
          id="quick-capture-text"
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder="What's on your mind? — a thought, a list, a fact to remember…"
          rows={6}
          className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-indigo-500/60 focus:border-indigo-500/60 resize-none"
        />
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onPickImage}
          disabled={uploading || image !== null}
          className={
            'inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs ' +
            (uploading || image !== null
              ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
              : 'bg-gray-800 text-gray-300 hover:bg-gray-700')
          }
          title="Attach image"
        >
          📎 {uploading ? 'Uploading…' : image ? 'Image attached' : 'Attach image'}
        </button>

        {image && (
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-900/40 border border-indigo-700/50 px-2 py-1 text-xs text-indigo-200">
            <span className="truncate max-w-[12rem]">{image.filename}</span>
            <button
              type="button"
              onClick={onRemoveImage}
              className="text-indigo-300 hover:text-white"
              aria-label="Remove image"
            >
              ✕
            </button>
          </span>
        )}
      </div>

      {workspaceId == null && (
        <div className="rounded-lg border border-amber-700/60 bg-amber-900/20 px-3 py-2 text-xs text-amber-200">
          No workspace is active. Open the sidebar and pick one before saving.
        </div>
      )}

      {workspaceName && workspaceId != null && (
        <p className="text-xs text-gray-500">
          Captures inherit{' '}
          <span className="text-gray-300">{workspaceName}</span>'s skill set
          and domain conventions.
        </p>
      )}
    </div>
  )
}

function ConfirmView({
  intents,
  accepted,
  setAccepted,
  commitErrors,
}: {
  intents: CaptureIntent[]
  accepted: boolean[]
  setAccepted: (next: boolean[]) => void
  commitErrors: string[]
}) {
  const toggle = (idx: number) => {
    const next = accepted.slice()
    next[idx] = !next[idx]
    setAccepted(next)
  }

  return (
    <div className="space-y-3">
      <div className="text-sm text-gray-300">
        Smart Capture extracted {pluralize(intents.length, 'intent')}. Untick any
        you don't want to save.
      </div>

      <ul className="space-y-2">
        {intents.map((intent, idx) => (
          <li
            key={idx}
            className={
              'rounded-lg border px-3 py-2 ' +
              (accepted[idx]
                ? 'border-indigo-700/60 bg-indigo-900/20'
                : 'border-gray-700 bg-gray-800/50 opacity-70')
            }
          >
            <label className="flex items-start gap-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={accepted[idx]}
                onChange={() => toggle(idx)}
                className="mt-1 accent-indigo-500"
              />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-gray-400">
                    {prettyDomainName(intent.domain)}
                  </span>
                  {intent.needs_more_info && (
                    <span className="text-[10px] uppercase tracking-wider text-amber-300 bg-amber-900/30 px-1.5 py-0.5 rounded">
                      needs more info
                    </span>
                  )}
                </div>
                <div className="text-sm text-gray-100 mt-0.5">{intent.summary}</div>
              </div>
            </label>
          </li>
        ))}
      </ul>

      {commitErrors.length > 0 && (
        <div className="rounded-lg border border-red-700/60 bg-red-900/20 px-3 py-2 text-xs text-red-200 space-y-1">
          <div className="font-medium">Some captures failed to save:</div>
          {commitErrors.map((e, i) => (
            <div key={i} className="font-mono">
              • {e}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StatusView({
  icon,
  title,
  caption,
}: {
  icon: string
  title: string
  caption: string
}) {
  return (
    <div className="flex flex-col items-center justify-center py-10 gap-2 text-center">
      <div className="text-3xl">{icon}</div>
      <div className="text-base text-gray-100">{title}</div>
      <div className="text-xs text-gray-500">{caption}</div>
    </div>
  )
}

function ExtractErrorView({
  message,
  retryable,
  hasText,
}: {
  message: string
  retryable: boolean
  hasText: boolean
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-red-700/60 bg-red-900/20 px-3 py-3">
        <div className="text-sm font-medium text-red-200 mb-1">
          Smart Capture failed
        </div>
        <div className="text-xs text-red-300">{message}</div>
      </div>
      <div className="text-xs text-gray-400 space-y-1">
        {retryable && <div>You can retry, or save your text verbatim as a raw note.</div>}
        {!hasText && (
          <div>
            Type something first if you want to save it as a raw note — empty
            captures aren't written.
          </div>
        )}
        <div>
          Raw notes go to <code className="text-gray-300">/knowledge/captures/</code>{' '}
          and are searchable by <code className="text-gray-300">recall</code>.
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Misc helpers
// ---------------------------------------------------------------------------

/**
 * Map smart-capture domain slugs to user-facing labels for the success
 * summary and confirm view headers. Falls back to the slug verbatim
 * for any unknown domain so new domains added in the n8n workflow
 * still display sensibly without a frontend update.
 */
function prettyDomainName(domain: string): string {
  const map: Record<string, string> = {
    knowledge_fact: 'knowledge note',
    shopping_list: 'shopping list item',
    project: 'project note',
    recipe: 'recipe',
    cook_log: 'cook log entry',
    tool: 'tool',
    saw_blade: 'saw blade',
    router_bit: 'router bit',
    wood: 'wood entry',
    album: 'album',
    manual: 'manual',
    house_room: 'house room',
    other: 'note',
  }
  return map[domain] ?? domain.replace(/_/g, ' ')
}
