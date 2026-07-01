/**
 * Per-conversation capture visibility ("Shared" vs "Private").
 *
 * Controls the visibility the Context Harvester applies to facts auto-learned
 * from what you type. It's a per-conversation *mode* (sticky in sessionStorage),
 * so the toggle UI lives in the conversation header (ChatHeader) — not the input
 * row. InputArea reads the value at send time via `readVisibility`.
 *
 * Default 'shared' (the household shares context by design); the user flips a
 * conversation to 'private' when they don't want it fed into shared memory.
 */
import { create } from 'zustand'

export type CaptureVisibility = 'private' | 'shared'

const KEY = 'bh-capture-visibility'

/** Authoritative read for a conversation — used at send time. Defaults to shared. */
export function readVisibility(convId: number | null | undefined): CaptureVisibility {
  if (!convId) return 'shared'
  try {
    const map = JSON.parse(sessionStorage.getItem(KEY) || '{}')
    return map[convId] === 'private' ? 'private' : 'shared'
  } catch {
    return 'shared'
  }
}

function writeVisibility(convId: number | null | undefined, v: CaptureVisibility) {
  if (!convId) return
  try {
    const map = JSON.parse(sessionStorage.getItem(KEY) || '{}')
    map[convId] = v
    sessionStorage.setItem(KEY, JSON.stringify(map))
  } catch {
    /* sessionStorage unavailable — in-memory store still drives the UI */
  }
}

interface CaptureVisibilityState {
  convId: number | null
  visibility: CaptureVisibility
  /** Load the sticky choice for a conversation (call on active-conversation change). */
  syncTo: (convId: number | null | undefined) => void
  toggle: () => void
}

export const useCaptureVisibility = create<CaptureVisibilityState>((set, get) => ({
  convId: null,
  visibility: 'shared',
  syncTo: (convId) => set({ convId: convId ?? null, visibility: readVisibility(convId) }),
  toggle: () => {
    const next: CaptureVisibility = get().visibility === 'shared' ? 'private' : 'shared'
    writeVisibility(get().convId, next)
    set({ visibility: next })
  },
}))
