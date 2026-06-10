import { create } from 'zustand'

export type ToastType = 'error' | 'success' | 'info'

export interface Toast {
  id: number
  type: ToastType
  message: string
}

interface ToastState {
  toasts: Toast[]
  push: (message: string, type?: ToastType, durationMs?: number) => number
  dismiss: (id: number) => void
}

let nextId = 1

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push: (message, type = 'info', durationMs = 5000) => {
    const id = nextId++
    set(state => ({ toasts: [...state.toasts, { id, type, message }] }))
    if (durationMs > 0) {
      setTimeout(() => get().dismiss(id), durationMs)
    }
    return id
  },
  dismiss: (id) => set(state => ({ toasts: state.toasts.filter(t => t.id !== id) })),
}))

/**
 * Convenience helpers callable from non-React code (api client, websocket
 * service) where hooks aren't available. They read the store imperatively.
 */
export const toast = {
  error: (message: string, durationMs = 7000) =>
    useToastStore.getState().push(message, 'error', durationMs),
  success: (message: string, durationMs?: number) =>
    useToastStore.getState().push(message, 'success', durationMs),
  info: (message: string, durationMs?: number) =>
    useToastStore.getState().push(message, 'info', durationMs),
}
