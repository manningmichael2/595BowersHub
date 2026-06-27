import { useConfirmStore } from '../stores/confirm'
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogAction,
  AlertDialogCancel,
} from './ui/AlertDialog'

/**
 * Host for the themed confirm dialog. Mount once near the app root (next to
 * <Toaster/>). Renders the single pending request from the confirm store
 * through the Radix-backed AlertDialog primitive (R2.2) — which provides the
 * focus trap/return, ESC handling, and scroll lock that used to be hand-rolled
 * here. The confirm store API is unchanged.
 *
 * ESC / overlay-dismiss → cancel (resolve false); the confirm button is
 * auto-focused so Enter confirms, matching window.confirm() flow.
 */
export default function ConfirmDialog() {
  const request = useConfirmStore((s) => s.request)
  const resolve = useConfirmStore((s) => s.resolve)

  return (
    <AlertDialog
      open={!!request}
      onOpenChange={(open) => {
        if (!open) resolve(false)
      }}
    >
      {request && (
        <AlertDialogContent>
          <AlertDialogHeader>
            {request.title ? (
              <AlertDialogTitle>{request.title}</AlertDialogTitle>
            ) : (
              <AlertDialogTitle className="sr-only">Confirm</AlertDialogTitle>
            )}
            <AlertDialogDescription>{request.message}</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel onClick={() => resolve(false)}>
              {request.cancelLabel || 'Cancel'}
            </AlertDialogCancel>
            <AlertDialogAction autoFocus danger={request.danger} onClick={() => resolve(true)}>
              {request.confirmLabel || 'Confirm'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      )}
    </AlertDialog>
  )
}
