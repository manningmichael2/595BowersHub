/**
 * Web Push subscription handshake.
 *
 * The Notifications "web push" preference is the user's *intent*; actual
 * delivery requires this browser to hold a Push subscription registered with
 * the backend. These helpers run that handshake when the toggle flips:
 *
 *   enableWebPush()  — request Notification permission, subscribe via the SW's
 *                      PushManager using the server VAPID key, POST the
 *                      subscription to the backend. Throws (with a
 *                      user-presentable message) if any step fails.
 *   disableWebPush() — unsubscribe locally and tell the backend to forget it.
 *
 * The toggle should only be reachable when the server reports web push
 * available (it has VAPID keys); `browserSupportsWebPush()` additionally gates
 * on this browser exposing the APIs.
 */
import { api } from './api'

export function browserSupportsWebPush(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    'serviceWorker' in navigator &&
    typeof window !== 'undefined' &&
    'PushManager' in window &&
    'Notification' in window
  )
}

// VAPID keys are URL-safe base64; PushManager wants a Uint8Array. Build it over
// an explicit ArrayBuffer so the type is `Uint8Array<ArrayBuffer>` (a valid
// BufferSource) rather than the generic `ArrayBufferLike` lib.dom rejects.
function urlBase64ToUint8Array(base64String: string): Uint8Array<ArrayBuffer> {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  const output = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i)
  return output
}

/**
 * Subscribe this browser to web push and register it with the backend.
 * Throws an Error with a user-facing message on any failure.
 */
export async function enableWebPush(): Promise<void> {
  if (!browserSupportsWebPush()) {
    throw new Error('This browser does not support web push.')
  }

  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    throw new Error('Notification permission was not granted.')
  }

  // The VAPID public key is required to create the subscription.
  const { data } = await api.get('/api/me/push/key')
  if (!data?.enabled || !data?.public_key) {
    throw new Error('Web push is not configured on the server.')
  }

  const reg = await navigator.serviceWorker.ready

  // Reuse an existing subscription if present; otherwise create one.
  let sub = await reg.pushManager.getSubscription()
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(data.public_key),
    })
  }

  await api.post('/api/me/push/subscribe', sub.toJSON())
}

/**
 * Unsubscribe this browser and tell the backend to drop the subscription.
 * Best-effort — never throws (turning a feature off shouldn't error out).
 */
export async function disableWebPush(): Promise<void> {
  try {
    if (!browserSupportsWebPush()) return
    const reg = await navigator.serviceWorker.ready
    const sub = await reg.pushManager.getSubscription()
    if (!sub) return
    const endpoint = sub.endpoint
    await sub.unsubscribe().catch(() => {})
    await api.post('/api/me/push/unsubscribe', { endpoint }).catch(() => {})
  } catch {
    // Swallow — the preference is already off; a failed cleanup is non-fatal.
  }
}
