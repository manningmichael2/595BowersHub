/**
 * WebSocket client: connects, authenticates, handles streaming events,
 * auto-reconnects with exponential backoff.
 */

import { useAuthStore } from '../stores/auth'
import { useConversationStore } from '../stores/conversation'

type ConnectionStatus = 'connecting' | 'connected' | 'disconnected' | 'reconnecting'

class WebSocketClient {
  private ws: WebSocket | null = null
  private reconnectAttempts = 0
  private maxReconnectDelay = 30000
  private reconnectTimer: number | null = null
  private messageQueue: any[] = []

  status: ConnectionStatus = 'disconnected'
  onStatusChange: ((status: ConnectionStatus) => void) | null = null

  connect() {
    const token = useAuthStore.getState().accessToken
    if (!token) {
      // Cold-start race: the auth store fires `refreshAuth()` on import,
      // and AppShell calls `connect()` immediately on mount — usually
      // before that refresh resolves. Schedule a reconnect so we retry
      // once the access token lands instead of staying disconnected
      // forever and quietly making the chat look broken.
      this.scheduleReconnect()
      return
    }

    this.setStatus('connecting')

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const wsUrl = `${protocol}//${window.location.host}/ws/chat`

    this.ws = new WebSocket(wsUrl)

    this.ws.onopen = () => {
      // Send auth message
      this.ws!.send(JSON.stringify({ type: 'auth', token }))
    }

    this.ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      this.handleMessage(data)
    }

    this.ws.onclose = (event) => {
      this.setStatus('disconnected')
      // Server signals a bad/expired access token with close code 4001.
      // Refresh the access token before scheduling the reconnect so the
      // next connect attempt presents a fresh credential. If the refresh
      // fails the auth store will clear the user; the reconnect loop
      // becomes a no-op.
      if (event.code === 4001) {
        useAuthStore
          .getState()
          .refreshAuth()
          .finally(() => this.scheduleReconnect())
      } else {
        this.scheduleReconnect()
      }
    }

    this.ws.onerror = () => {
      this.ws?.close()
    }
  }

  disconnect() {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
    this.reconnectAttempts = 0
    this.setStatus('disconnected')
  }

  sendMessage(conversationId: number, content: string, model: string = 'auto', attachments: any[] = []) {
    const msg = {
      type: 'message',
      conversation_id: conversationId,
      content,
      model,
      attachments,
    }

    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    } else {
      // Queue for when reconnected
      this.messageQueue.push(msg)
    }
  }

  cancelMessage(conversationId: number) {
    const msg = { type: 'cancel', conversation_id: conversationId }
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  private handleMessage(data: any) {
    const store = useConversationStore.getState()

    switch (data.type) {
      case 'auth_success':
        this.setStatus('connected')
        this.reconnectAttempts = 0
        // Send queued messages
        while (this.messageQueue.length > 0) {
          const msg = this.messageQueue.shift()
          this.ws?.send(JSON.stringify(msg))
        }
        break

      case 'typing':
        store.setStreaming(true)
        break

      case 'token':
        store.appendStreamToken(data.data)
        break

      case 'skill_status':
        store.setSkillStatus(data.data)
        break

      case 'complete':
        store.addMessage(data.data)
        store.setSkillStatus(null)
        break

      case 'context_captured':
        // Could show a toast or indicator
        break

      case 'cancelled':
        store.setStreaming(false)
        store.setSkillStatus(null)
        // The server already persisted a cancellation marker; just clear the
        // streaming state. Optional: surface a toast.
        break

      case 'error':
        store.setStreaming(false)
        store.setSkillStatus(null)
        // Could show error toast
        console.error('WebSocket error:', data.data?.message)
        break

      case 'pong':
        break

      default:
        console.log('Unknown WS message:', data.type)
    }
  }

  private setStatus(status: ConnectionStatus) {
    this.status = status
    this.onStatusChange?.(status)
  }

  private scheduleReconnect() {
    if (this.reconnectTimer) return

    this.reconnectAttempts++
    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts - 1), this.maxReconnectDelay)

    this.setStatus('reconnecting')
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, delay)
  }
}

export const wsClient = new WebSocketClient()
