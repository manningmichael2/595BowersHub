import { create } from 'zustand'
import { parseLoose } from '../lib/validate'
import { UserSchema, AuthResponseSchema, RefreshResponseSchema, type User } from '../schemas/auth'

export type { User }

interface AuthState {
  user: User | null
  accessToken: string | null
  refreshToken: string | null
  isLoading: boolean
  error: string | null
  isRefreshing: boolean

  login: (email: string, password: string) => Promise<void>
  register: (email: string, password: string, displayName: string, inviteToken: string) => Promise<void>
  logout: () => void
  refreshAuth: () => Promise<boolean>
  clearError: () => void
}

const BASE_URL = ''

// Single-flight refresh. The refresh token ROTATES on every /api/auth/refresh
// (the response carries a new refresh_token that replaces the old one), so the
// old token is single-use. On app load many requests fire at once (workspaces,
// conversations, settings, dashboard…); if the access token is stale they all
// 401 together. Without de-duping, each would POST /refresh with the same
// rotating token — the first consumes it, the rest fail and trigger a spurious
// logout, leaving stores with swallowed 401s and empty data (blank sidebar).
// Holding one shared promise means concurrent callers await the SAME refresh
// and then retry with the single freshly-rotated token.
let inFlightRefresh: Promise<boolean> | null = null

async function rawFetch(path: string, options: RequestInit) {
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
  })
  if (!res.ok) {
    const data = await res.json().catch(() => ({ detail: 'Request failed' }))
    throw { response: { status: res.status, data } }
  }
  return res.json()
}

export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  accessToken: null,
  refreshToken: null,
  isLoading: false,
  error: null,
  isRefreshing: false,

  login: async (email, password) => {
    set({ isLoading: true, error: null })
    try {
      const data = await rawFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      const { access_token, refresh_token, user } = parseLoose(
        AuthResponseSchema,
        data,
        'POST /api/auth/login'
      )
      set({ user, accessToken: access_token, refreshToken: refresh_token, isLoading: false })
      localStorage.setItem('refreshToken', refresh_token)
      localStorage.setItem('user', JSON.stringify(user))
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Login failed'
      set({ error: msg, isLoading: false })
      throw new Error(msg)
    }
  },

  register: async (email, password, displayName, inviteToken) => {
    set({ isLoading: true, error: null })
    try {
      await rawFetch('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify({ email, password, display_name: displayName, invite_token: inviteToken }),
      })
      await get().login(email, password)
    } catch (err: any) {
      const msg = err.response?.data?.detail || 'Registration failed'
      set({ error: msg, isLoading: false })
      throw new Error(msg)
    }
  },

  logout: () => {
    const { refreshToken } = get()
    if (refreshToken) {
      // Best-effort logout call
      fetch('/api/auth/logout', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${get().accessToken}`,
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      }).catch(() => {})
    }
    set({ user: null, accessToken: null, refreshToken: null, error: null })
    localStorage.removeItem('refreshToken')
    localStorage.removeItem('user')
  },

  refreshAuth: async () => {
    // Concurrent callers share the one in-flight refresh (see inFlightRefresh).
    if (inFlightRefresh) return inFlightRefresh

    const run = async (): Promise<boolean> => {
      const refreshToken = get().refreshToken || localStorage.getItem('refreshToken')
      if (!refreshToken) return false

      set({ isRefreshing: true })
      try {
        const data = await rawFetch('/api/auth/refresh', {
          method: 'POST',
          body: JSON.stringify({ refresh_token: refreshToken }),
        })
        const { access_token, refresh_token: new_refresh_token } = parseLoose(
          RefreshResponseSchema,
          data,
          'POST /api/auth/refresh'
        )
        set({
          accessToken: access_token,
          refreshToken: new_refresh_token,
          isRefreshing: false,
        })
        localStorage.setItem('refreshToken', new_refresh_token)
        return true
      } catch {
        // Clean logout on refresh failure. Send the user to the login page
        // so they get a clear next action instead of staring at a stale
        // chat that pretends to work — except when we're already there
        // (e.g. the login form's own initial-state probe failed) so we
        // don't bounce-loop the route.
        set({
          user: null,
          accessToken: null,
          refreshToken: null,
          isRefreshing: false,
        })
        localStorage.removeItem('refreshToken')
        localStorage.removeItem('user')
        if (
          typeof window !== 'undefined' &&
          !window.location.pathname.startsWith('/login') &&
          !window.location.pathname.startsWith('/register')
        ) {
          window.location.href = '/login'
        }
        return false
      }
    }

    inFlightRefresh = run().finally(() => { inFlightRefresh = null })
    return inFlightRefresh
  },

  clearError: () => set({ error: null }),
}))

// Restore session on app load
const savedUser = localStorage.getItem('user')
const savedRefresh = localStorage.getItem('refreshToken')
if (savedUser && savedRefresh) {
  try {
    const user = JSON.parse(savedUser)
    useAuthStore.setState({ user, refreshToken: savedRefresh })
    // Try to refresh once
    useAuthStore.getState().refreshAuth().then(success => {
      if (!success) {
        useAuthStore.setState({ user: null })
      }
    })
  } catch {
    localStorage.removeItem('user')
    localStorage.removeItem('refreshToken')
  }
}
