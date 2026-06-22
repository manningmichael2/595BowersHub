import { useToastStore, type ToastType } from '../stores/toast'

const STYLES: Record<ToastType, string> = {
  error: 'bg-red-600 text-white',
  success: 'bg-green-600 text-white',
  info: 'bg-neutral-800 text-white',
}

/**
 * Global toast container. Mounted once near the app root; renders the toast
 * queue from the toast store. Auto-dismissal is handled by the store.
 */
export default function Toaster() {
  const toasts = useToastStore(s => s.toasts)
  const dismiss = useToastStore(s => s.dismiss)

  if (toasts.length === 0) return null

  return (
    <div
      className="fixed bottom-4 right-4 z-[9999] flex flex-col gap-2 max-w-sm"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map(t => (
        <div
          key={t.id}
          role="alert"
          className={`flex items-start gap-3 rounded-lg px-4 py-3 shadow-lg ${STYLES[t.type]}`}
        >
          <span className="text-sm flex-1 break-words">{t.message}</span>
          {t.action && (
            <button
              onClick={() => { t.action!.onClick(); dismiss(t.id) }}
              className="shrink-0 rounded bg-white/20 hover:bg-white/30 px-2 py-0.5 text-xs font-medium"
            >
              {t.action.label}
            </button>
          )}
          <button
            onClick={() => dismiss(t.id)}
            aria-label="Dismiss notification"
            className="shrink-0 opacity-70 hover:opacity-100 leading-none text-lg"
          >
            ×
          </button>
        </div>
      ))}
    </div>
  )
}
