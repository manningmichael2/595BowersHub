import { useEffect, useRef } from 'react'
import { useConfirmStore } from '../stores/confirm'

/**
 * Host for the themed confirm dialog. Mount once near the app root (next to
 * <Toaster/>). Renders the single pending request from the confirm store and
 * resolves it on the user's choice. Esc cancels; Enter confirms; the confirm
 * button is auto-focused so keyboard flow matches window.confirm().
 */
export default function ConfirmDialog() {
  const request = useConfirmStore(s => s.request)
  const resolve = useConfirmStore(s => s.resolve)
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!request) return
    confirmRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { e.preventDefault(); resolve(false) }
      if (e.key === 'Enter') { e.preventDefault(); resolve(true) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [request, resolve])

  if (!request) return null

  return (
    <div
      className="fixed inset-0 z-[10000] flex items-center justify-center bg-black/60 px-4"
      role="presentation"
      onClick={() => resolve(false)}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-label={request.title || 'Confirm'}
        className="w-full max-w-sm rounded-xl border border-border bg-surface p-5 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {request.title && (
          <h2 className="mb-1 text-base font-semibold text-text">{request.title}</h2>
        )}
        <p className="text-sm text-text-muted">{request.message}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => resolve(false)}
            className="rounded-lg border border-border px-3 py-2 text-sm font-medium text-text-muted transition-colors hover:text-text"
          >
            {request.cancelLabel || 'Cancel'}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={() => resolve(true)}
            className="rounded-lg px-3 py-2 text-sm font-medium text-on-primary transition-[filter] hover:brightness-110"
            style={{ backgroundColor: request.danger ? 'var(--color-danger)' : 'var(--color-primary)' }}
          >
            {request.confirmLabel || 'Confirm'}
          </button>
        </div>
      </div>
    </div>
  )
}
