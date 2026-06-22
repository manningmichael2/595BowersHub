import { create } from 'zustand'

export type ToastType = 'error' | 'success' | 'info'

/** Optional action button rendered in the toast (e.g. "Reload"). */
export interface ToastAction {
  label: string
  onClick: () => void
}

export interface Toast {
  id: number
  type: ToastType
  message: string
  action?: ToastAction
}

interface ToastState {
  toasts: Toast[]
  push: (message: string, type?: ToastType, durationMs?: number, action?: ToastAction) => number
  dismiss: (id: number) => void
}

let nextId = 1

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],
  push: (message, type = 'info', durationMs = 5000, action) => {
    const id = nextId++
    set(state => ({ toasts: [...state.toasts, { id, type, message, action }] }))
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
  error: (message: string, durationMs = 7000, action?: ToastAction) =>
    useToastStore.getState().push(message, 'error', durationMs, action),
  success: (message: string, durationMs?: number, action?: ToastAction) =>
    useToastStore.getState().push(message, 'success', durationMs, action),
  info: (message: string, durationMs?: number, action?: ToastAction) =>
    useToastStore.getState().push(message, 'info', durationMs, action),
}
