import { AlertCircle, CheckCircle2, Info, X, type LucideIcon } from 'lucide-react'
import { useToastStore, type ToastType } from '../stores/toast'
import { cn } from './ui/cn'

/**
 * Per-type styling, fully tokenized (R2.4 — closes the C6 global-toast tail).
 * Bold colored backgrounds are kept (an error toast should be loud), with the
 * readable `on-*` foreground and an action/close button tinted in that
 * foreground via the alpha-composable `on-*` tokens (T1/T2). `info` sits on the
 * neutral surface with a border.
 */
const STYLES: Record<ToastType, { container: string; button: string; Icon: LucideIcon }> = {
  error: {
    container: 'bg-danger text-on-danger',
    button: 'bg-on-danger/20 hover:bg-on-danger/30',
    Icon: AlertCircle,
  },
  success: {
    container: 'bg-success text-on-success',
    button: 'bg-on-success/20 hover:bg-on-success/30',
    Icon: CheckCircle2,
  },
  info: {
    container: 'border border-border bg-surface text-text',
    button: 'bg-text/10 hover:bg-text/20',
    Icon: Info,
  },
}

/**
 * Global toast container. Mounted once near the app root; renders the toast
 * queue from the toast store. Auto-dismissal + queue live in the store (API
 * unchanged); this only re-skins. Layers at `z-toast` (above modals/portals).
 */
export default function Toaster() {
  const toasts = useToastStore((s) => s.toasts)
  const dismiss = useToastStore((s) => s.dismiss)

  if (toasts.length === 0) return null

  return (
    <div
      className="fixed bottom-4 right-4 z-toast flex max-w-sm flex-col gap-2"
      role="region"
      aria-label="Notifications"
    >
      {toasts.map((t) => {
        const { container, button, Icon } = STYLES[t.type]
        return (
          <div
            key={t.id}
            role="alert"
            className={cn(
              'flex items-start gap-3 rounded-md px-4 py-3 shadow-elevation-3',
              container,
            )}
          >
            <Icon className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span className="flex-1 break-words text-sm">{t.message}</span>
            {t.action && (
              <button
                onClick={() => {
                  t.action!.onClick()
                  dismiss(t.id)
                }}
                className={cn(
                  'shrink-0 rounded px-2 py-0.5 text-xs font-medium transition-colors',
                  button,
                )}
              >
                {t.action.label}
              </button>
            )}
            <button
              onClick={() => dismiss(t.id)}
              aria-label="Dismiss notification"
              className={cn(
                'shrink-0 rounded leading-none opacity-70 transition-opacity hover:opacity-100',
              )}
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        )
      })}
    </div>
  )
}
