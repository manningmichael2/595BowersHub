import { create } from 'zustand'

/**
 * Themed confirm dialog — a promise-based replacement for window.confirm().
 *
 * The native dialog renders OS chrome that ignores the app theme and breaks
 * the "real app" feel. This store holds at most one pending request; the host
 * (<ConfirmDialog/>, mounted once near the app root) renders it and resolves
 * the promise when the user chooses.
 *
 * Usage (from any component or imperative code):
 *   if (await confirm({ message: 'Delete this?', confirmLabel: 'Delete', danger: true })) { ... }
 */
export interface ConfirmOptions {
  message: string
  title?: string
  confirmLabel?: string
  cancelLabel?: string
  /** Style the confirm button as a destructive action. */
  danger?: boolean
}

interface ConfirmRequest extends ConfirmOptions {
  id: number
  resolve: (ok: boolean) => void
}

interface ConfirmState {
  request: ConfirmRequest | null
  open: (opts: ConfirmOptions) => Promise<boolean>
  resolve: (ok: boolean) => void
}

let nextId = 1

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  request: null,
  open: (opts) =>
    new Promise<boolean>((resolve) => {
      // If a request is already pending, resolve it false so we never strand it.
      const prev = get().request
      if (prev) prev.resolve(false)
      set({ request: { ...opts, id: nextId++, resolve } })
    }),
  resolve: (ok) => {
    const req = get().request
    if (req) {
      req.resolve(ok)
      set({ request: null })
    }
  },
}))

/** Imperative helper, callable from anywhere (mirrors `toast`). */
export function confirm(opts: ConfirmOptions): Promise<boolean> {
  return useConfirmStore.getState().open(opts)
}
