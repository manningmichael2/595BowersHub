/**
 * Client-side error reporting.
 *
 * Motivation: a silent client crash (uncaught error, unhandled rejection, or a
 * render error the ErrorBoundary catches) is invisible to the admin — you only
 * find out when a user complains. This ships those to `POST /api/telemetry/
 * client-error`, which stores them and (rate-limited) pings the admin via
 * Pushover. Viewing is via the existing DB browser (`public.bh_client_errors`).
 *
 * Design constraints:
 *  - Must NEVER throw or recurse (a failing reporter can't itself raise).
 *  - Uses a bare fetch (not the api client) so it never triggers the 401
 *    refresh/logout machinery — a telemetry failure must not log the user out.
 *  - Client-side dedupe + cap so a tight error loop can't flood the network.
 */
import { useAuthStore } from '../stores/auth'

interface ClientErrorPayload {
  message: string
  stack?: string
  url?: string
}

const recentSignatures = new Map<string, number>()
const DEDUPE_WINDOW_MS = 60_000
let sentThisSession = 0
const MAX_PER_SESSION = 50

function signatureOf(p: ClientErrorPayload): string {
  const firstStackLine = (p.stack || '').split('\n')[1]?.trim() ?? ''
  return `${p.message}::${firstStackLine}`
}

export function reportClientError(payload: ClientErrorPayload): void {
  try {
    if (sentThisSession >= MAX_PER_SESSION) return
    const sig = signatureOf(payload)
    const now = Date.now()
    const last = recentSignatures.get(sig)
    if (last && now - last < DEDUPE_WINDOW_MS) return
    recentSignatures.set(sig, now)
    sentThisSession++

    const token = useAuthStore.getState().accessToken
    // Unauthenticated errors (e.g. on the login screen) are skipped: the
    // endpoint requires auth, and pre-login crashes are rare and low-value.
    if (!token) return

    void fetch('/api/telemetry/client-error', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        message: payload.message.slice(0, 2000),
        stack: payload.stack?.slice(0, 8000),
        url: payload.url ?? (typeof location !== 'undefined' ? location.href : undefined),
      }),
      // Don't keep the tab alive for this; best-effort only.
      keepalive: true,
    }).catch(() => {})
  } catch {
    // Reporting must never break the app.
  }
}

/** Attach global handlers for uncaught errors and unhandled promise rejections. */
export function installGlobalErrorReporting(): void {
  if (typeof window === 'undefined') return

  window.addEventListener('error', (e: ErrorEvent) => {
    reportClientError({
      message: e.message || 'Uncaught error',
      stack: e.error?.stack,
      url: e.filename,
    })
  })

  window.addEventListener('unhandledrejection', (e: PromiseRejectionEvent) => {
    const reason = e.reason
    const message =
      reason instanceof Error ? reason.message : `Unhandled rejection: ${String(reason)}`
    reportClientError({ message, stack: reason instanceof Error ? reason.stack : undefined })
  })
}
